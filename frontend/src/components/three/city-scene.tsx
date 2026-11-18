"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { Stage } from "./stage";
import { AnchorSetter, useAnchors, useProjectedAnchor } from "./anchor";
import { fmtInt } from "@/lib/format";

export interface CityRow { id: number; name: string; client: string; received: number; edited: number; handled: number; pending: number }
export interface CityEditor { id: number; name: string; value: number }
export interface CityFocus { client?: string; project?: number; editor?: number }

const PALETTE = ["#3fc47e", "#ff6b73", "#9be8bb", "#f0b040", "#1f9d5a", "#8aa397"];
// Clients stand side by side along X; a client's projects line up behind each other along Z.
// That fills a wide canvas, and lets the camera swing round to the side to read one client's projects.
const GAP_CLIENT = 2.5, GAP_PROJECT = 2.0, BAR = 0.9, MAX_H = 4.2, LABEL_PX = 110, EDITOR_GAP = 0.42;
interface Tip { x: number; y: number; title: string; lines: string[]; color: string }

interface Layout {
  clients: { name: string; x: number; color: string; cols: number; cz: number }[];
  bars: { row: CityRow; x: number; z: number; h: number; color: string }[];
  center: THREE.Vector3; width: number; depth: number;
}

function buildLayout(rows: CityRow[]): Layout {
  const max = Math.max(1, ...rows.map((r) => r.received));
  const byClient = new Map<string, CityRow[]>();
  rows.forEach((r) => byClient.set(r.client, [...(byClient.get(r.client) ?? []), r]));
  const order = [...byClient.entries()].sort((a, b) => b[1].reduce((s, r) => s + r.received, 0) - a[1].reduce((s, r) => s + r.received, 0));
  const clients: Layout["clients"] = [];
  const bars: Layout["bars"] = [];
  order.forEach(([name, list], ci) => {
    const color = PALETTE[ci % PALETTE.length];
    const x = ci * GAP_CLIENT;
    list.sort((a, b) => b.received - a.received).forEach((row, pi) => {
      bars.push({ row, x, z: pi * GAP_PROJECT, h: Math.max(0.08, (row.received / max) * MAX_H), color });
    });
    clients.push({ name, x, color, cols: list.length, cz: ((list.length - 1) * GAP_PROJECT) / 2 });
  });
  const cols = Math.max(1, ...clients.map((c) => c.cols));
  const width = (clients.length - 1) * GAP_CLIENT, depth = (cols - 1) * GAP_PROJECT;
  return { clients, bars, center: new THREE.Vector3(width / 2, 1.1, depth / 2), width, depth };
}

/* ------------------------------------------------------------------ camera rig with drill transitions */
function CameraRig({ layout, editors, focus }: { layout: Layout; editors: CityEditor[]; focus: CityFocus }) {
  const controls = useRef<OrbitControlsImpl>(null);
  const { camera, size } = useThree();
  const anim = useRef(2.4); // seconds of guided motion left after a focus change
  const aspect = size.width / Math.max(size.height, 1);
  const key = `${focus.client}|${focus.project}|${focus.editor}|${layout.bars.length}|${editors.length}`;

  const target = useMemo(() => {
    const L = layout;
    const bar = L.bars.find((b) => b.row.id === focus.project);
    const client = L.clients.find((c) => c.name === focus.client);
    if (bar && editors.length) {
      // Editor level: stand in front of the row of editor pillars
      const idx = editors.findIndex((e) => e.id === focus.editor);
      const ex = bar.x + (idx >= 0 ? (idx - (editors.length - 1) / 2) * EDITOR_GAP : 0);
      return { p: new THREE.Vector3(ex + 0.6, 4.1, bar.z + 5.4), l: new THREE.Vector3(ex, 1.1, bar.z + 1.0) };
    }
    if (bar) return { p: new THREE.Vector3(bar.x + 1.8, bar.h * 0.5 + 4.2, bar.z + 4.8), l: new THREE.Vector3(bar.x, bar.h * 0.4, bar.z) };
    if (client) {
      // Client level: move in and rise above the row so its projects read front to back
      return { p: new THREE.Vector3(client.x + 2.6, 7.0, client.cz + 8.2), l: new THREE.Vector3(client.x, 1.1, client.cz) };
    }
    // Overall: front-on and slightly above, far enough back to fit every client across the width
    const halfFov = (((camera as THREE.PerspectiveCamera).fov ?? 40) * Math.PI) / 360;
    const dist = Math.max(8, (L.width + 5) / (2 * Math.tan(halfFov) * aspect));
    return { p: new THREE.Vector3(L.center.x, 3.2 + dist * 0.38, L.center.z + dist), l: L.center.clone() };
  }, [layout, editors, focus.client, focus.project, focus.editor, aspect, camera]);

  useEffect(() => { anim.current = 2.4; }, [key]);

  useFrame((_, dt) => {
    const c = controls.current;
    if (!c) return;
    if (anim.current > 0) {
      const k = 1 - Math.exp(-dt * 3.2); // eased: quick start, soft landing
      camera.position.lerp(target.p, k);
      c.target.lerp(target.l, k);
      anim.current -= dt;
    }
    c.update();
  });

  return (
    <OrbitControls
      ref={controls} makeDefault enablePan={false} enableDamping dampingFactor={0.08}
      minDistance={3} maxDistance={32} maxPolarAngle={Math.PI / 2.15}
      onStart={() => { anim.current = 0; }} // the user grabbed the camera: stop guiding it
    />
  );
}

/* ------------------------------------------------------------------ bars */
function Bar({ x, z, h, color, dim, hot, onClick, onTip, tip, width = BAR }: {
  x: number; z: number; h: number; color: string; dim: boolean; hot: boolean; width?: number;
  onClick: () => void; onTip: (t: Tip | null) => void; tip: Omit<Tip, "x" | "y">;
}) {
  const mesh = useRef<THREE.Mesh>(null);
  const cur = useRef(0.01);
  const [hover, setHover] = useState(false);
  useFrame((_, dt) => {
    const m = mesh.current;
    if (!m) return;
    cur.current += (h - cur.current) * Math.min(1, dt * 5); // grows up from the floor
    m.scale.y = Math.max(cur.current, 0.01);
    m.position.y = m.scale.y / 2;
  });
  return (
    <mesh
      ref={mesh} position={[x, 0.005, z]} scale={[1, 0.01, 1]}
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      onPointerOver={(e) => { e.stopPropagation(); setHover(true); document.body.style.cursor = "pointer"; }}
      onPointerMove={(e) => {
        e.stopPropagation();
        const n = e.nativeEvent as PointerEvent;
        const box = (n.target as HTMLElement).getBoundingClientRect();
        onTip({ ...tip, x: n.clientX - box.left, y: n.clientY - box.top });
      }}
      onPointerOut={() => { setHover(false); onTip(null); document.body.style.cursor = ""; }}
    >
      <boxGeometry args={[width, 1, width]} />
      <meshStandardMaterial color={color} roughness={0.4} metalness={0.15} transparent opacity={dim ? 0.28 : 1}
        emissive={color} emissiveIntensity={hover || hot ? 0.45 : 0.08} />
    </mesh>
  );
}

function Anchor({ id, x, y, z, set, worldWidth = 1.5, visible = true }: {
  id: string; x: number; y: number; z: number; set: AnchorSetter; worldWidth?: number; visible?: boolean;
}) {
  const g = useRef<THREE.Group>(null);
  useProjectedAnchor(g, id, (i, px, py, s) => set(i, px, py, s, visible), worldWidth, LABEL_PX);
  return <group ref={g} position={[x, y, z]} />;
}

function Scene({ rows, editors, focus, set, onTip, onPickProject, onPickEditor }: {
  rows: CityRow[]; editors: CityEditor[]; focus: CityFocus; set: AnchorSetter; onTip: (t: Tip | null) => void;
  onPickProject: (r: CityRow) => void; onPickEditor: (id: number) => void;
}) {
  const layout = useMemo(() => buildLayout(rows), [rows]);
  const focusBar = layout.bars.find((b) => b.row.id === focus.project);
  const maxEd = Math.max(1, ...editors.map((e) => e.value));
  const anyFocus = !!(focus.client || focus.project);

  return (
    <>
      <CameraRig layout={layout} editors={editors} focus={focus} />
      <gridHelper args={[Math.max(layout.width, layout.depth) + 14, 28, "#3f6b52", "#27402f"]} position={[layout.center.x, 0, layout.center.z]} />

      {layout.clients.map((c) => (
        <Anchor key={`c:${c.name}`} id={`c:${c.name}`} x={c.x} y={0.05} z={layout.depth + 1.5} set={set} worldWidth={1.7} />
      ))}

      {layout.bars.map((b) => {
        const inClient = !focus.client || focus.client === b.row.client;
        const isProj = focus.project === b.row.id;
        const dim = anyFocus && !(isProj || (!focus.project && inClient));
        return (
          <group key={b.row.id}>
            <Bar
              x={b.x} z={b.z} h={b.h} color={b.color} dim={dim} hot={isProj}
              onClick={() => onPickProject(b.row)} onTip={onTip}
              tip={{ title: b.row.name, color: b.color, lines: [`${b.row.client}`, `Received ${fmtInt(b.row.received)}`, `Edited ${fmtInt(b.row.edited)}`, `Handled ${fmtInt(b.row.handled)}`, `Still pending ${fmtInt(b.row.pending)}`] }}
            />
            <Anchor id={`p:${b.row.id}`} x={b.x} y={b.h + 0.4} z={b.z} set={set} worldWidth={1.5}
              visible={isProj || (!focus.project && focus.client === b.row.client)} />
          </group>
        );
      })}

      {focusBar && editors.map((e, i) => {
        const ex = focusBar.x + (i - (editors.length - 1) / 2) * EDITOR_GAP;
        const eh = Math.max(0.06, (e.value / maxEd) * Math.min(2.2, Math.max(0.9, focusBar.h * 0.75)));
        const ez = focusBar.z + GAP_PROJECT / 2;
        return (
          <group key={e.id}>
            <Bar
              x={ex} z={ez} h={eh} width={0.3} color={focus.editor === e.id ? "#e5484d" : "#b8e6cb"}
              dim={!!focus.editor && focus.editor !== e.id} hot={focus.editor === e.id}
              onClick={() => onPickEditor(e.id)} onTip={onTip}
              tip={{ title: e.name, color: "#7cc99b", lines: [`Handled ${fmtInt(e.value)} in this project`] }}
            />
            <Anchor id={`e:${e.id}`} x={ex} y={eh + 0.3} z={ez} set={set} worldWidth={0.8} />
          </group>
        );
      })}
    </>
  );
}

export default function CityScene({ rows, editors, focus, onPickClient, onPickProject, onPickEditor, height = 460 }: {
  rows: CityRow[]; editors: CityEditor[]; focus: CityFocus; height?: number;
  onPickClient: (c: string) => void; onPickProject: (r: CityRow) => void; onPickEditor: (id: number) => void;
}) {
  const { set, ref } = useAnchors();
  const [tip, setTip] = useState<Tip | null>(null);
  const layout = useMemo(() => buildLayout(rows), [rows]);

  const overlay = (
    <>
      {layout.clients.map((c) => (
        <button key={c.name} ref={ref(`c:${c.name}`)} onClick={() => onPickClient(c.name)}
          className="pointer-events-auto absolute left-0 top-0 rounded-lg px-2 py-1 text-center text-[15px] font-semibold will-change-transform focus-visible:outline focus-visible:outline-2"
          style={{ width: LABEL_PX, opacity: 0, transformOrigin: "center", color: c.color, background: "hsl(var(--card) / 0.75)" }}>
          {c.name}
        </button>
      ))}
      {rows.map((r) => (
        <div key={r.id} ref={ref(`p:${r.id}`)} aria-hidden className="absolute left-0 top-0 text-center text-[13px] font-medium will-change-transform"
          style={{ width: LABEL_PX, opacity: 0, transformOrigin: "center", textShadow: "0 1px 3px hsl(var(--background))" }}>
          {r.name}
        </div>
      ))}
      {editors.map((e) => (
        <div key={e.id} ref={ref(`e:${e.id}`)} aria-hidden className="absolute left-0 top-0 text-center text-[12px] will-change-transform"
          style={{ width: LABEL_PX, opacity: 0, transformOrigin: "center", textShadow: "0 1px 3px hsl(var(--background))" }}>
          {e.name.split(" ")[0]}
        </div>
      ))}
      {tip && (
        <div className="glass absolute z-10 whitespace-nowrap px-2.5 py-1.5 text-xs" style={{ left: tip.x + 14, top: tip.y + 14 }}>
          <div className="mb-0.5 flex items-center gap-1.5 font-semibold">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: tip.color }} />{tip.title}
          </div>
          {tip.lines.map((l) => <div key={l} className="tabular-nums text-muted-foreground">{l}</div>)}
        </div>
      )}
    </>
  );

  return (
    <Stage
      height={height} camera={{ position: [layout.center.x, 8, 16], fov: 40 }} overlay={overlay}
      ariaLabel={`3D bar city of ${rows.length} projects across ${layout.clients.length} clients. Bar height is forms received.`}
    >
      <Scene rows={rows} editors={editors} focus={focus} set={set} onTip={setTip}
        onPickProject={onPickProject} onPickEditor={onPickEditor} />
    </Stage>
  );
}
