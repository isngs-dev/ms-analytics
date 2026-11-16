"use client";
import { useRef, useState } from "react";
import { useFrame } from "@react-three/fiber";
import { Float, RoundedBox } from "@react-three/drei";
import * as THREE from "three";
import { Stage } from "./stage";
import { useFitCamera } from "./fit";
import { AnchorSetter, useAnchors, useProjectedAnchor } from "./anchor";
import { useCountUp } from "@/components/widgets";
import { fmtInt } from "@/lib/format";

export interface HeroItem {
  key: string; label: string; value: number | null | undefined; hint: string; color: string; onClick?: () => void;
}

const GAP = 2.2;
const LABEL_PX = 230; // CSS width of a tile label before perspective scaling

function TileLabel({ item, setRef }: { item: HeroItem; setRef: (el: HTMLElement | null) => void }) {
  const shown = useCountUp(item.value ?? 0);
  return (
    <button
      ref={setRef}
      onClick={item.onClick}
      aria-label={`${item.label}: ${item.value ?? "no data"}. Show records`}
      className="pointer-events-auto absolute left-0 top-0 rounded-xl px-3 py-2 text-left text-white will-change-transform focus-visible:outline focus-visible:outline-2 focus-visible:outline-white"
      style={{ width: LABEL_PX, opacity: 0, transformOrigin: "center" }}
    >
      <span className="block text-[13px] font-semibold uppercase tracking-wider opacity-90">{item.label}</span>
      <span className="block text-[44px] font-semibold leading-tight tabular-nums">{item.value == null ? "–" : fmtInt(shown)}</span>
      <span className="block text-[12px] opacity-85">{item.hint}</span>
    </button>
  );
}

function Tile({ item, x, index, set }: { item: HeroItem; x: number; index: number; set: AnchorSetter }) {
  const body = useRef<THREE.Group>(null);
  const [hover, setHover] = useState(false);
  const base = new THREE.Color(item.color);
  useProjectedAnchor(body, item.key, set, 1.8, LABEL_PX, [0, 0, 0.18]);

  useFrame((_, dt) => {
    const g = body.current;
    if (!g) return;
    g.scale.setScalar(THREE.MathUtils.lerp(g.scale.x, hover ? 1.07 : 1, Math.min(1, dt * 8)));
  });

  return (
    <Float speed={1.3 + index * 0.15} rotationIntensity={0.18} floatIntensity={0.55} floatingRange={[-0.07, 0.07]}>
      <group position={[x, 0, -Math.abs(x) * 0.12]} rotation={[0, -x * 0.05, 0]}>
        <group ref={body}>
          <RoundedBox
            args={[2, 1.28, 0.3]} radius={0.1} smoothness={5}
            onClick={item.onClick}
            onPointerOver={() => { setHover(true); document.body.style.cursor = "pointer"; }}
            onPointerOut={() => { setHover(false); document.body.style.cursor = ""; }}
          >
            <meshPhysicalMaterial color={base} roughness={0.3} metalness={0.1} clearcoat={0.7} clearcoatRoughness={0.25}
              emissive={base} emissiveIntensity={hover ? 0.35 : 0.12} />
          </RoundedBox>
          <mesh position={[0, 0.56, 0.16]}>
            <boxGeometry args={[1.7, 0.05, 0.02]} />
            <meshBasicMaterial color="#ffffff" transparent opacity={0.55} />
          </mesh>
        </group>
      </group>
    </Float>
  );
}

function Rig({ items, set }: { items: HeroItem[]; set: AnchorSetter }) {
  const rig = useRef<THREE.Group>(null);
  useFitCamera(items.length * GAP + 0.4, 2.1);
  // mouse parallax: the whole row leans toward the pointer
  useFrame(({ pointer }, dt) => {
    const g = rig.current;
    if (!g) return;
    const k = Math.min(1, dt * 4);
    g.rotation.y = THREE.MathUtils.lerp(g.rotation.y, pointer.x * 0.3, k);
    g.rotation.x = THREE.MathUtils.lerp(g.rotation.x, -pointer.y * 0.14, k);
    g.position.x = THREE.MathUtils.lerp(g.position.x, pointer.x * 0.25, k);
  });
  return (
    <group ref={rig}>
      {items.map((it, i) => (
        <Tile key={it.key} item={it} index={i} set={set} x={(i - (items.length - 1) / 2) * GAP} />
      ))}
    </group>
  );
}

export default function HeroScene({ items, height = 250 }: { items: HeroItem[]; height?: number }) {
  const { set, ref } = useAnchors();
  const summary = items.map((i) => `${i.label} ${i.value ?? "n/a"}`).join(", ");
  return (
    <Stage
      height={height} ariaLabel={`Key figures: ${summary}`} camera={{ position: [0, 0, 9], fov: 32 }}
      overlay={items.map((it) => <TileLabel key={it.key} item={it} setRef={ref(it.key)} />)}
    >
      <Rig items={items} set={set} />
    </Stage>
  );
}
