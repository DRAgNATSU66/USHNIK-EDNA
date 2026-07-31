import React, { useEffect, useRef } from "react";
import * as THREE from "three";

/**
 * Rotating green/red double-helix visualization.
 * Self-contained Three.js scene sized to its parent container.
 */
export default function DnaHelixViz({ height = 260 }) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const width = container.clientWidth || 300;
    const initialHeight = container.clientHeight || height;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, width / initialHeight, 0.1, 1000);
    camera.position.z = 2;

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setSize(width, initialHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

    const helixGroup = new THREE.Group();
    const numPoints = 120;
    const helixRadius = 0.5;
    const helixHeight = 1.6;
    const disposables = [];

    const buildStrand = (sign, color, size, opacity, renderOrder) => {
      const points = [];
      for (let i = 0; i < numPoints; i++) {
        const t = (i / (numPoints - 1)) * Math.PI * 6;
        const x = sign * helixRadius * Math.cos(t);
        const y = helixHeight * (i / numPoints) - helixHeight / 2;
        const z = sign * helixRadius * Math.sin(t);
        points.push(new THREE.Vector3(x, y, z));
      }
      const geometry = new THREE.BufferGeometry().setFromPoints(points);
      const material = new THREE.PointsMaterial({
        color,
        size,
        blending: THREE.AdditiveBlending,
        transparent: true,
        opacity,
        sizeAttenuation: true,
        depthTest: false,
        depthWrite: false,
      });
      const strand = new THREE.Points(geometry, material);
      strand.renderOrder = renderOrder;
      disposables.push(geometry, material);
      return strand;
    };

    // Green strand + glow
    helixGroup.add(buildStrand(1, 0x00e65a, 0.065, 1.0, 2));
    helixGroup.add(buildStrand(1, 0x00e65a, 0.12, 0.18, 1));
    // Red strand + glow (opposite phase)
    helixGroup.add(buildStrand(-1, 0xff3b3b, 0.06, 1.0, 2));
    helixGroup.add(buildStrand(-1, 0xff3b3b, 0.12, 0.18, 1));

    scene.add(helixGroup);

    const pointLight = new THREE.PointLight(0x00ff88, 0.8, 100);
    pointLight.position.set(0, 0, 8);
    scene.add(pointLight);

    let rafId;
    const animate = () => {
      rafId = requestAnimationFrame(animate);
      helixGroup.rotation.y += 0.006;
      renderer.render(scene, camera);
    };
    animate();

    const resizeObserver = new ResizeObserver(() => {
      const w = container.clientWidth || width;
      const h = container.clientHeight || initialHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    });
    resizeObserver.observe(container);

    return () => {
      cancelAnimationFrame(rafId);
      resizeObserver.disconnect();
      disposables.forEach((d) => d.dispose());
      renderer.dispose();
    };
  }, [height]);

  return (
    <div ref={containerRef} style={{ width: "100%", height }}>
      <canvas ref={canvasRef} style={{ width: "100%", height: "100%", display: "block" }} />
    </div>
  );
}
