"use client";
import { useMemo, useRef, useState } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { Stage } from "./stage";
import { useFitCamera } from "./fit";
import { AnchorSetter, useAnchors, useProjectedAnchor } from "./anchor";
import { fmtInt } from "@/lib/format";

export interface Slice { name: string; value: number; color: string; onClick?: () => void }
export interface DonutDef { title: string; center: string; slices: Slice[] }
interface Tip { x: number; y: number; name: string; value: number; pct: number; color: string }

const R = 1.35, r = 0.82, DEPTH = 0.42, GAP_ANGLE = 0.045, LABEL_PX = 120;

function sliceGeometry(a0: number, a1: number) {
  const s = new THREE.Shape();
  s.absarc(0, 0, R, a0, a1, false);
  s.absarc(0, 0, r, a1, a0, true);
  s.closePath();
  return new THREE.ExtrudeGeometry(s, { depth: DEPTH, bevelEnabled: true, bevelSize: 0.03, bevelThickness: 0.03, bevelSegments: 2, curveSegments: 56 });
}

function Donut({ def, y, set, onTip }: { def: DonutDef; y: number; set: AnchorSetter; onTip: (t: Tip | null) => void }) {
  const tilt = useRef<THREE.Group>(null);
  const spin = useRef<THREE.Group>(null);
  const [hover, setHover] = useState<number | null>(null);
  const total = def.slices.reduce((a, s) => a + s.value, 0);
  useProjectedAnchor(tilt, def.title, set, 1.2, LABEL_PX, [0, 0, DEPTH]);

  const parts = useMemo(() => {
    let acc = Math.PI / 2; // start at 12 o'clock
    const nonZero = def.slices.filter((s) => s.value > 0).length;
    return def.slices.map((s) => {
      const span = total ? (s.value / total) * Math.PI * 2 : 0;
      const gap = nonZero > 1 ? GAP_ANGLE : 0;
      const a0 = acc + gap / 2, a1 = acc + span - gap / 2;
      acc += span;
      return { s, geo: span > 0.02 ? sliceGeometry(a0, a1) : null, mid: (a0 + a1) / 2, pct: total ? (100 * s.value) / total : 0 };
    });
  }, [def.slices, total]);

  useFrame((_, dt) => {
    if (spin.current && hover === null) spin.current.rotation.z += dt * 0.32;
  });

  return (
    <group ref={tilt} position={[0, y, 0]} rotation={[-0.95, 0, 0]}>
      <group ref={spin}>
        {parts.map((p, i) => {
          if (!p.geo) return null;
          const on = hover === i;
          const out = on ? 0.14 : 0;
          return (
            <mesh
              key={p.s.name} geometry={p.geo}
              position={[Math.cos(p.mid) * out, Math.sin(p.mid) * out, on ? 0.12 : 0]}
              onClick={(e) => { e.stopPropagation(); p.s.onClick?.(); }}
              onPointerMove={(e) => {
                e.stopPropagation();
                const n = e.nativeEvent as PointerEvent;
                const box = (n.target as HTMLElement).getBoundingClientRect();
                onTip({ x: n.clientX - box.left, y: n.clientY - box.top, name: p.s.name, value: p.s.value, pct: p.pct, color: p.s.color });
              }}
              onPointerOver={(e) => { e.stopPropagation(); setHover(i); document.body.style.cursor = p.s.onClick ? "pointer" : ""; }}
              onPointerOut={() => { setHover(null); onTip(null); document.body.style.cursor = ""; }}
            >
              <meshPhysicalMaterial color={p.s.color} roughness={0.35} metalness={0.1} clearcoat={0.6}
                emissive={p.s.color} emissiveIntensity={on ? 0.35 : 0.1} />
            </mesh>
          );
        })}
      </group>
    </group>
  );
}

function Rig({ donuts, vertical, set, onTip }: { donuts: DonutDef[]; vertical: boolean; set: AnchorSetter; onTip: (t: Tip | null) => void }) {
  const pitch = 2 * R + 0.8;
  useFitCamera(vertical ? 2 * R + 1.6 : donuts.length * pitch, vertical ? donuts.length * pitch * 0.82 : 2 * R * 0.8 + 1);
  return (
    <>
      {donuts.map((d, i) => (
        <Donut key={d.title} def={d} set={set} onTip={onTip} y={vertical ? ((donuts.length - 1) / 2 - i) * pitch * 0.82 : 0} />
      ))}
    </>
  );
}

export default function DonutScene({ donuts, height = 440, vertical = true }: { donuts: DonutDef[]; height?: number; vertical?: boolean }) {
  const { set, ref } = useAnchors();
  const [tip, setTip] = useState<Tip | null>(null);
  const label = donuts.map((d) => `${d.title}: ${d.slices.map((s) => `${s.name} ${s.value}`).join(", ")}`).join(". ");
  return (
    <Stage
      height={height} ariaLabel={label} camera={{ position: [0, 0, 9], fov: 34 }}
      overlay={
        <>
          {donuts.map((d) => (
            <div key={d.title} ref={ref(d.title)} aria-hidden className="absolute left-0 top-0 text-center will-change-transform"
              style={{ width: LABEL_PX, opacity: 0, transformOrigin: "center" }}>
              <div className="text-[34px] font-semibold leading-none tabular-nums">{d.center}</div>
              <div className="mt-1 text-[14px] text-muted-foreground">{d.title}</div>
            </div>
          ))}
          {tip && (
            <div className="glass absolute z-10 whitespace-nowrap px-2.5 py-1.5 text-xs" style={{ left: tip.x + 14, top: tip.y + 14 }}>
              <span className="mr-1.5 inline-block h-2 w-2 rounded-full" style={{ background: tip.color }} />
              {tip.name}: <strong className="tabular-nums">{fmtInt(tip.value)}</strong> ({tip.pct.toFixed(0)}%)
            </div>
          )}
        </>
      }
    >
      <Rig donuts={donuts} vertical={vertical} set={set} onTip={setTip} />
    </Stage>
  );
}
