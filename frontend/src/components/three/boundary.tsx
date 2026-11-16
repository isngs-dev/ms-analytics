"use client";
import { Component } from "react";

/**
 * Catches WebGL / shader failures and lets the caller render its 2D fallback instead.
 * Kept in its own file with no three.js imports so pages can use it without pulling 3D code
 * into their first-load bundle (the scenes themselves are loaded with next/dynamic).
 */
export class Boundary extends Component<{ fallback: React.ReactNode; children: React.ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(e: unknown) { console.warn("3D scene failed, using 2D fallback", e); }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}
