// OrbitalVisualization.jsx
import React, { useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";

function CentralSphere() {
  const ref = useRef();
  useFrame(() => {
    if (ref.current) ref.current.rotation.y += 0.002;
  });
  return (
    <mesh ref={ref}>
      <sphereGeometry args={[2, 64, 64]} />
      <meshStandardMaterial
        color="#00d4ff"
        emissive="#00d4ff"
        emissiveIntensity={0.4}
        roughness={0.3}
        metalness={0.1}
      />
    </mesh>
  );
}

function OrbitRing({ color, radius, tilt = [0, 0, 0] }) {
  return (
    <line rotation={tilt}>
      <bufferGeometry
        attach="geometry"
        {...new THREE.BufferGeometry().setFromPoints(
          new THREE.Path()
            .absarc(0, 0, radius, 0, Math.PI * 2, true)
            .getPoints(128)
        )}
      />
      <lineBasicMaterial attach="material" color={color} />
    </line>
  );
}

export default function OrbitalVisualization({ height = "60vh" }) {
  return (
    <div style={{ width: "100%", height }}>
      <Canvas camera={{ position: [0, 5, 15], fov: 60 }}>
        <ambientLight intensity={0.6} />
        <directionalLight position={[5, 5, 5]} />
        <CentralSphere />
        <OrbitRing color="#2563eb" radius={4} tilt={[Math.PI / 2, 0, 0]} />
        <OrbitRing color="#10b981" radius={4.5} tilt={[0, 0, 0]} />
        <OrbitRing color="#8b5cf6" radius={5} tilt={[Math.PI / 4, 0, 0]} />
        <OrbitRing color="#f59e0b" radius={5.5} tilt={[-Math.PI / 4, 0, 0]} />
        <OrbitRing color="#ef4444" radius={6} tilt={[0, Math.PI / 4, 0]} />
        <OrbitRing color="#fbbf24" radius={6.5} tilt={[0, 0, Math.PI / 2]} />
        <OrbitControls enablePan={false} />
      </Canvas>
    </div>
  );
}
