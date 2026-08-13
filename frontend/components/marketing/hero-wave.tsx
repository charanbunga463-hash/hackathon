"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

/**
 * The signature centerpiece — a glowing rainbow particle "mountain" rendered
 * in real WebGL, in the spirit of antigravity.google.
 *
 * A dense grid of points is displaced into a single gaussian peak (the wave /
 * "A" silhouette) inside the vertex shader, tinted by height from deep blue at
 * the base up through green and gold to a hot red crown, and drifting with a
 * slow traveling ripple. Everything is additive-blended on black so the dots
 * read as light rather than paint.
 *
 * The whole scene is pure math on the GPU: no textures, no models, no network.
 */

const vertexShader = /* glsl */ `
  uniform float uTime;
  uniform float uSize;
  attribute vec2 aGrid;      // normalized grid coord in [-1, 1]
  varying float vHeight;     // normalized peak height for colouring
  varying float vFade;       // edge fade so the field dissolves at the rim

  void main() {
    vec2 g = aGrid;
    float x = position.x;
    float z = position.z;

    // Single gaussian peak — the mountain / bell silhouette.
    float r2 = (x * x) / 6.2 + (z * z) / 6.2;
    float peak = exp(-r2) * 3.05;

    // Slow traveling ripples layered on top for life.
    float ripple =
      sin(x * 1.7 + uTime * 0.9) * 0.10 +
      sin(z * 2.1 - uTime * 0.7) * 0.10 +
      sin((x + z) * 1.1 + uTime * 0.5) * 0.06;

    float radial = length(g);
    float rim = smoothstep(1.0, 0.55, radial); // fade out toward the edges
    float y = peak + ripple * rim;

    vHeight = clamp(peak / 3.05, 0.0, 1.0);
    vFade = rim;

    vec3 pos = vec3(x, y, z);
    vec4 mv = modelViewMatrix * vec4(pos, 1.0);

    // Crown dots ride a little larger; distance attenuation keeps depth.
    float sizeBoost = 0.6 + vHeight * 1.4;
    gl_PointSize = uSize * sizeBoost * (11.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;

const fragmentShader = /* glsl */ `
  precision highp float;
  varying float vHeight;
  varying float vFade;

  // Deep blue -> cyan -> green -> gold -> red, keyed on height.
  vec3 palette(float t) {
    vec3 c0 = vec3(0.05, 0.10, 0.55); // base blue
    vec3 c1 = vec3(0.10, 0.55, 0.95); // sky
    vec3 c2 = vec3(0.15, 0.85, 0.70); // teal-green
    vec3 c3 = vec3(0.98, 0.80, 0.25); // gold
    vec3 c4 = vec3(0.98, 0.28, 0.18); // crown red
    vec3 c = mix(c0, c1, smoothstep(0.0, 0.30, t));
    c = mix(c, c2, smoothstep(0.28, 0.55, t));
    c = mix(c, c3, smoothstep(0.55, 0.80, t));
    c = mix(c, c4, smoothstep(0.80, 1.0, t));
    return c;
  }

  void main() {
    // Round, soft-edged glowing dot.
    vec2 uv = gl_PointCoord - 0.5;
    float d = length(uv);
    if (d > 0.5) discard;
    float glow = smoothstep(0.5, 0.0, d);

    vec3 col = palette(vHeight);
    // Lift brightness at the crown so the peak blooms.
    col += vHeight * 0.35;

    float alpha = glow * (0.35 + vHeight * 0.65) * vFade;
    gl_FragColor = vec4(col, alpha);
  }
`;

function ParticleWave() {
  const pointsRef = useRef<THREE.Points>(null);
  const materialRef = useRef<THREE.ShaderMaterial>(null);

  const { positions, grid } = useMemo(() => {
    const N = 190; // grid resolution per side
    const span = 9; // world units across
    const positions = new Float32Array(N * N * 3);
    const grid = new Float32Array(N * N * 2);
    let i = 0;
    for (let ix = 0; ix < N; ix++) {
      for (let iz = 0; iz < N; iz++) {
        const u = ix / (N - 1); // 0..1
        const v = iz / (N - 1);
        const x = (u - 0.5) * span;
        const z = (v - 0.5) * span;
        positions[i * 3 + 0] = x;
        positions[i * 3 + 1] = 0;
        positions[i * 3 + 2] = z;
        grid[i * 2 + 0] = (u - 0.5) * 2;
        grid[i * 2 + 1] = (v - 0.5) * 2;
        i++;
      }
    }
    return { positions, grid };
  }, []);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uSize: { value: 2.4 },
    }),
    [],
  );

  useFrame((state) => {
    if (materialRef.current) {
      materialRef.current.uniforms.uTime.value = state.clock.elapsedTime;
    }
    if (pointsRef.current) {
      // Gentle continuous turntable, like the reference.
      pointsRef.current.rotation.y = Math.sin(state.clock.elapsedTime * 0.12) * 0.35;
    }
  });

  return (
    <points ref={pointsRef} rotation={[-0.35, 0, 0]} position={[0, -0.9, 0]}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          args={[positions, 3]}
        />
        <bufferAttribute attach="attributes-aGrid" args={[grid, 2]} />
      </bufferGeometry>
      <shaderMaterial
        ref={materialRef}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}

export function HeroWave() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  if (!mounted) return null;

  return (
    <Canvas
      className="!absolute inset-0"
      camera={{ position: [0, 1.6, 8.5], fov: 42 }}
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
    >
      <ParticleWave />
    </Canvas>
  );
}
