"use client";
import { useEffect } from "react";
import { useThree } from "@react-three/fiber";
import type { PerspectiveCamera } from "three";

/** Pulls the camera back (or in) so a world-space box of `width` x `height` always fits the canvas. */
export function useFitCamera(width: number, height: number, margin = 1.08) {
  const { camera, size, invalidate } = useThree();
  useEffect(() => {
    const cam = camera as PerspectiveCamera;
    const aspect = size.width / Math.max(size.height, 1);
    const halfFov = ((cam.fov ?? 40) * Math.PI) / 360;
    const needH = Math.max(height, width / aspect) * margin;
    cam.position.z = needH / (2 * Math.tan(halfFov));
    cam.updateProjectionMatrix();
    invalidate();
  }, [camera, size.width, size.height, width, height, margin, invalidate]);
}
