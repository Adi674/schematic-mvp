"""
OpenCV-based Geometry Extractor for schematics.

Extracts line segments (wires) and junctions (dots, intersections) from
an image, matching them against component bounding boxes.
"""

import logging
from typing import List, Tuple, Optional, Dict, Any
from src.schematic.schema import (
    WireSegmentFact,
    JunctionFact,
    ComponentFact,
    ValidationStatus,
    RefState
)

logger = logging.getLogger(__name__)

# Try to import cv2 and numpy; handle import errors gracefully
OPENCV_AVAILABLE = False
try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    logger.warning("OpenCV or NumPy is not available. Geometry extraction will run in fallback mode.")


def line_intersection(
    line1: Tuple[float, float, float, float],
    line2: Tuple[float, float, float, float],
    tolerance: float = 3.0
) -> Optional[Tuple[float, float]]:
    """
    Computes the mathematical intersection of two line segments, if any,
    within the segment boundaries (extended by tolerance).
    """
    if not OPENCV_AVAILABLE:
        return None

    x1, y1, x2, y2 = line1
    x3, y3, x4, y4 = line2

    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-6:
        return None  # Parallel or collinear

    # Intersection point using determinants
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denom
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denom

    # Check if the intersection point lies within the bounding box of both segments (with tolerance)
    def within(val: float, limit1: float, limit2: float) -> bool:
        return min(limit1, limit2) - tolerance <= val <= max(limit1, limit2) + tolerance

    if (within(px, x1, x2) and within(py, y1, y2) and
            within(px, x3, x4) and within(py, y3, y4)):
        return (px, py)

    return None


class GeometryExtractor:
    """Uses OpenCV to extract wire lines and junctions from schematic images."""

    def __init__(self, proximity_tolerance_pixels: float = 12.0):
        self.proximity_tolerance = proximity_tolerance_pixels

    def extract_geometry(
        self,
        image_bytes: bytes,
        components: List[ComponentFact]
    ) -> Tuple[List[WireSegmentFact], List[JunctionFact], bool]:
        """
        Processes image_bytes to find wire segments and junctions.
        Returns:
            (wire_segments, junctions, success_flag)
        """
        if not OPENCV_AVAILABLE:
            logger.info("OpenCV is not available; returning empty geometry facts (fallback mode).")
            return [], [], False

        try:
            # Decode image from bytes
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                logger.error("Failed to decode image from bytes.")
                return [], [], False

            h, w = img.shape[:2]
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # Preprocessing: Threshold to invert black-on-white schematic
            # Threshold chosen to catch thin dark lines on light background
            _, thresh = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY_INV)

            # 1. Line Detection using Probabilistic Hough Transform
            # Tune parameters for clean schematic line traces
            raw_lines = cv2.HoughLinesP(
                thresh,
                rho=1,
                theta=np.pi / 180,
                threshold=25,
                minLineLength=6,
                maxLineGap=8
            )

            detected_wires: List[WireSegmentFact] = []
            line_coords: List[Tuple[float, float, float, float]] = []

            if raw_lines is not None:
                for idx, line in enumerate(raw_lines):
                    flat = line.flatten()
                    if len(flat) != 4:
                        continue
                    x1, y1, x2, y2 = flat
                    line_coords.append((float(x1), float(y1), float(x2), float(y2)))
                    detected_wires.append(
                        WireSegmentFact(
                            wire_id=f"W_GEO_{idx+1:03d}",
                            start=[float(x1), float(y1)],
                            end=[float(x2), float(y2)],
                            points=[[float(x1), float(y1)], [float(x2), float(y2)]],
                            source="geometry",
                            model_confidence=1.0,
                            validation_status=ValidationStatus.OK
                        )
                    )

            # 2. Junction Detection via intersection of lines & contour dots
            junctions: List[JunctionFact] = []
            junction_points: List[Tuple[float, float]] = []

            # Method A: Detect explicit intersection dots via contour area/circularity
            # Schematic dots are usually small solid circles (15px to 120px area)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if 10.0 <= area <= 150.0:
                    # Check circularity
                    perimeter = cv2.arcLength(cnt, True)
                    if perimeter > 0:
                        circularity = 4 * np.pi * area / (perimeter * perimeter)
                        if circularity >= 0.6:  # Reasonably circular
                            M = cv2.moments(cnt)
                            if M["m00"] != 0:
                                cx = float(M["m10"] / M["m00"])
                                cy = float(M["m01"] / M["m00"])
                                junction_points.append((cx, cy))

            # Method B: Mathematical line segment intersections
            # Find points where detected line segments cross/meet
            for i in range(len(line_coords)):
                for j in range(i + 1, len(line_coords)):
                    pt = line_intersection(line_coords[i], line_coords[j], tolerance=3.0)
                    if pt:
                        # Avoid duplicates
                        if not any(np.linalg.norm(np.array(pt) - np.array(existing)) < 5.0 for existing in junction_points):
                            junction_points.append(pt)

            # Assemble detected junctions
            for idx, pt in enumerate(junction_points):
                # Find connected wires
                connected = []
                for wire in detected_wires:
                    w_coords = np.array([wire.start, wire.end])
                    # Distance from point to segment
                    p = np.array(pt)
                    d = np.min([np.linalg.norm(w_coords[0] - p), np.linalg.norm(w_coords[1] - p)])
                    if d <= self.proximity_tolerance:
                        connected.append(wire.wire_id)

                junctions.append(
                    JunctionFact(
                        junction_id=f"J_GEO_{idx+1:03d}",
                        position=[pt[0], pt[1]],
                        connected_wires=connected,
                        source="geometry"
                    )
                )

            # 3. Mark invalid component bboxes that don't match any wire
            # A component without any close wire segment is suspicious / potential invalid bbox
            for comp in components:
                if comp.evidence and comp.evidence.bbox:
                    x1, y1, x2, y2 = comp.evidence.bbox
                    # Expand bbox by tolerance
                    cx1 = x1 - self.proximity_tolerance
                    cy1 = y1 - self.proximity_tolerance
                    cx2 = x2 + self.proximity_tolerance
                    cy2 = y2 + self.proximity_tolerance

                    # Check if any wire intersects or starts/ends near this box
                    has_close_wire = False
                    for wire in detected_wires:
                        # Simple check: start or end point inside expanded box
                        wx1, wy1 = wire.start
                        wx2, wy2 = wire.end
                        if (cx1 <= wx1 <= cx2 and cy1 <= wy1 <= cy2) or (cx1 <= wx2 <= cx2 and cy1 <= wy2 <= cy2):
                            has_close_wire = True
                            break

                    # If no wires near it, lower the confidence or tag it
                    if not has_close_wire and len(detected_wires) > 0:
                        # Do not override manually visible comps, but flag validation status
                        if comp.ref_state != RefState.VISIBLE:
                            comp.validation_status = ValidationStatus.UNVERIFIED

            return detected_wires, junctions, True

        except Exception as e:
            logger.error(f"Error in geometry extraction: {e}", exc_info=True)
            return [], [], False
