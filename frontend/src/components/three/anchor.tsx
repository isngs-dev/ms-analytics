"use client";
import { useCallback, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

/**
 * DOM labels that follow 3D objects WITHOUT drei's <Html>.
 * <Html> mounts a second React root inside the canvas tree, which on React 19 throws
 * "synchronously unmount a root while React was already rendering" on unmount / Strict Mode.
 * Instead the labels live in an ordinary DOM overlay and the scene writes their transform
 * straight to the element every frame (no React state, no re-render).
 */
export type AnchorSetter = (id: string, x: number, y: number, scale: number, visible?: boolean) => void;

export function useAnchors() {
  const nodes = useRef(new Map<string, HTMLElement>());
  const set = useCallback<AnchorSetter>((id, x, y, scale, visible = true) => {
    const el = nodes.current.get(id);
    if (!el) return;
    el.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%) scale(${scale})`;
    el.style.opacity = visible ? "1" : "0";
  }, []);
  const ref = useCallback((id: string) => (el: HTMLElement | null) => {
    if (el) nodes.current.set(id, el);
    else nodes.current.delete(id);
  }, []);
  return { set, ref };
}

const v = new THREE.Vector3();
const off = new THREE.Vector3();
const tmp = new THREE.Vector3();

/**
 * Projects `object`'s world position to canvas pixels each frame and reports it.
 * `worldWidth` is how wide (in scene units) the DOM label should appear; `basePx` is its CSS width,
 * so the label scales with perspective like the object itself.
 */
export function useProjectedAnchor(
  object: React.RefObject<THREE.Object3D | null>, id: string, set: AnchorSetter, worldWidth: number, basePx: number,
  offset: [number, number, number] = [0, 0, 0],
) {
  useFrame(({ camera, size }) => {
    const o = object.current;
    if (!o) return;
    o.getWorldPosition(v);
    v.add(off.set(offset[0], offset[1], offset[2]));
    // depth along the view axis (not the straight-line distance, which would shrink off-centre labels)
    const dist = Math.max(0.01, -tmp.copy(v).applyMatrix4(camera.matrixWorldInverse).z);
    const fov = ((camera as THREE.PerspectiveCamera).fov * Math.PI) / 180;
    const ppu = size.height / (2 * Math.tan(fov / 2) * dist); // pixels per world unit at this depth
    v.project(camera);
    set(id, (v.x * 0.5 + 0.5) * size.width, (-v.y * 0.5 + 0.5) * size.height, (ppu * worldWidth) / basePx);
  });
}
