import React, { useEffect, useRef } from "react";

import * as THREE from "three";


/**
 * Stakeholder selector page with Three.js animated background:
 * - Dotted/pixel-style central shape that smoothly morphs between Sphere, Cuboid, Pyramid, Cylinder, Octahedron, and Dodecahedron (rainbow gradient).
 * - All shapes are significantly larger (75% larger than before) and use deterministic, uniform grid-like point placement for a consistent "pixel art" aesthetic.
 * - Pixels are larger, brighter, and more prominent.
 * - Morphing takes 5 seconds, followed by a 2-second hold.
 *
 * Props:
 * - onSelect(id) 	-> called when user clicks SELECT on a card
 */
export default function DashboardSelectionScreen({ onSelect = () => {} }) {
	const canvasRef = useRef(null);

	useEffect(() => {
		const canvas = canvasRef.current;
		if (!canvas) return;

		// Renderer setup
		const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
		renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
		renderer.setSize(window.innerWidth, window.innerHeight);
		renderer.setClearColor(0x000000, 0);

		// Scene & camera
		const scene = new THREE.Scene();
		const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 1000);
		camera.position.z = 4.5; // Adjusted camera back for larger shapes

		// Lighting
		const amb = new THREE.AmbientLight(0xffffff, 0.18);
		scene.add(amb);
		const dir = new THREE.DirectionalLight(0xffffff, 0.1);
		dir.position.set(5, 5, 5);
		scene.add(dir);

		const group = new THREE.Group();
		scene.add(group);

		// --- Shape Cycling Constants for Morphing ---
		const TRANSITION_DURATION = 5000; // 5 seconds for the morph (in milliseconds)
		const HOLD_DURATION = 2000; // 2 seconds hold time between morphs
		// Six shapes in the cycle:
		const SHAPE_NAMES = ['sphere', 'cuboid', 'pyramid', 'cylinder', 'octahedron', 'dodecahedron'];
		const POINT_COUNT = 1400; // Must be constant for morphing
		// New sizes (75% increase from previous)
		const SPHERE_RADIUS = 1.1953;
		const SHAPE_SIZE = 2.1375;

		let currentShapeIndex = 0;
		let lastSwitchTime = 0;
		let isMorphing = false;
		let shapePositions = {};


		// --- Shared Material for Rainbow Color Cycle ---
		const createSharedMaterial = () => {
			const initialHue = 0.8;
			const initialColor = new THREE.Color().setHSL(initialHue, 1.0, 0.55);
			return new THREE.PointsMaterial({
				size: 0.025, // Increased size for prominence
				color: initialColor,
				vertexColors: false,
				transparent: true,
				opacity: 1.0, // Increased opacity for prominence/glow
				blending: THREE.AdditiveBlending,
				depthTest: false,
				sizeAttenuation: true,
			});
		};

		const sharedMaterial = createSharedMaterial();


		// --- Shape Position Generators (return Float32Array) ---
		// Note: All functions must generate the same number of points (POINT_COUNT) in the returned array.

		// Generates a point cloud sphere (using Fibonacci sampling for uniform distribution)
		const generateDottedSpherePositions = (radius = SPHERE_RADIUS, points = POINT_COUNT) => {
			const pos = new Float32Array(points * 3);
			for (let i = 0; i < points; i++) {
				const phi = Math.acos(1 - 2 * (i + 0.5) / points);
				const theta = Math.PI * (1 + Math.sqrt(5)) * (i + 0.5);
				const x = Math.sin(phi) * Math.cos(theta);
				const y = Math.sin(phi) * Math.sin(theta);
				const z = Math.cos(phi);
				pos[i * 3 + 0] = x * radius;
				pos[i * 3 + 1] = y * radius;
				pos[i * 3 + 2] = z * radius;
			}
			return pos;
		};

		// Generates a point cloud cuboid using a deterministic grid pattern on each of the 6 faces.
		const generateDottedCuboidPositions = (size = SHAPE_SIZE, points = POINT_COUNT) => {
			const halfSize = size / 2;
			const pos = new Float32Array(points * 3);

			// Distribute 1400 points across 6 faces: 4 faces get 233, 2 faces get 234.
			const P_PER_FACE_BASE = 233;
			const REMAINDER_FACES = 2;

			// Faces definitions: {axis: fixed axis, value: fixed coordinate}
			const FACES = [
				{ axis: 'x', value: halfSize }, // +X
				{ axis: 'y', value: halfSize }, // +Y
				{ axis: 'z', value: halfSize }, // +Z
				{ axis: 'x', value: -halfSize }, // -X
				{ axis: 'y', value: -halfSize }, // -Y
				{ axis: 'z', value: -halfSize }, // -Z
			];

			let currentPointIndex = 0;

			for (let f = 0; f < 6; f++) {
				const numPoints = P_PER_FACE_BASE + (f < REMAINDER_FACES ? 1 : 0);

				const sqrtNumPoints = Math.sqrt(numPoints);
				const rows = Math.ceil(sqrtNumPoints);
				const cols = Math.ceil(numPoints / rows);

				const rowSpacing = size / (rows > 1 ? rows - 1 : 1);
				const colSpacing = size / (cols > 1 ? cols - 1 : 1);

				for (let r = 0; r < rows; r++) {
					for (let c = 0; c < cols; c++) {
						if (currentPointIndex >= points) break;

						const localIndex = r * cols + c;
						if (localIndex >= numPoints) continue;

						const v1 = r * rowSpacing - halfSize;
						const v2 = c * colSpacing - halfSize;

						const face = FACES[f];
						let x = 0, y = 0, z = 0;

						switch(face.axis) {
							case 'x': x = face.value; y = v1; z = v2; break;
							case 'y': y = face.value; x = v1; z = v2; break;
							case 'z': z = face.value; x = v1; y = v2; break;
						}

						pos[currentPointIndex * 3 + 0] = x;
						pos[currentPointIndex * 3 + 1] = y;
						pos[currentPointIndex * 3 + 2] = z;
						currentPointIndex++;
					}
				}
			}

			// Pad remaining indices
			const lastValidIndex = currentPointIndex > 0 ? currentPointIndex - 1 : 0;
			const lastX = pos[lastValidIndex * 3 + 0];
			const lastY = pos[lastValidIndex * 3 + 1];
			const lastZ = pos[lastValidIndex * 3 + 2];
			for (let i = currentPointIndex; i < points; i++) {
				pos[i * 3 + 0] = lastX;
				pos[i * 3 + 1] = lastY;
				pos[i * 3 + 2] = lastZ;
			}

			return pos;
		};

		// Generates a point cloud pyramid (tetrahedron) using a deterministic triangle grid on each of the 4 faces.
		const generateDottedPyramidPositions = (size = SHAPE_SIZE, points = POINT_COUNT) => {
			const pos = new Float32Array(points * 3);
			const P_PER_FACE = 350; // 1400 / 4 = 350
			const NUM_LINES = 26; // Generates 351 points (26*27/2), allowing us to use 350 uniformly.

			// Vertices of a centered tetrahedron
			const r = size / Math.sqrt(3);
			const h = size * Math.sqrt(3/8) * 1.5;

			const V = [
				new THREE.Vector3(r, -h/3, 0),
				new THREE.Vector3(-r/2, -h/3, r * Math.sqrt(3)/2),
				new THREE.Vector3(-r/2, -h/3, -r * Math.sqrt(3)/2),
				new THREE.Vector3(0, h * 2/3, 0) // Apex (index 3)
			];

			// Faces are defined by 3 vertices (Apex, Vb, Vc). Points will be generated from Apex towards Base.
			const FACES = [
				[V[3], V[0], V[1]],
				[V[3], V[1], V[2]],
				[V[3], V[2], V[0]],
				[V[0], V[2], V[1]] // Base face
			];

			let currentPointIndex = 0;

			for (let f = 0; f < 4; f++) {
				const numPoints = P_PER_FACE;
				const [vA, vB, vC] = FACES[f];

				let localPointCount = 0;

				// Loop from Apex (i=0) outwards to the base (i=NUM_LINES - 1)
				for (let i = 0; i < NUM_LINES; i++) {
					const t = i / (NUM_LINES - 1);

					const vStart = new THREE.Vector3().copy(vA).lerp(vB, t);
					const vEnd = new THREE.Vector3().copy(vA).lerp(vC, t);

					const pointsOnLine = i + 1;
					for (let j = 0; j < pointsOnLine; j++) {
						if (currentPointIndex >= points || localPointCount >= numPoints) break;

						const u = (pointsOnLine > 1) ? j / (pointsOnLine - 1) : 0;

						const p = vStart.clone().lerp(vEnd, u);

						pos[currentPointIndex * 3 + 0] = p.x;
						pos[currentPointIndex * 3 + 1] = p.y;
						pos[currentPointIndex * 3 + 2] = p.z;

						currentPointIndex++;
						localPointCount++;
					}
					if (currentPointIndex >= points || localPointCount >= numPoints) break;
				}
			}

			// Pad remaining points if necessary
			const lastValidIndex = currentPointIndex > 0 ? currentPointIndex - 1 : 0;
			const lastX = pos[lastValidIndex * 3 + 0];
			const lastY = pos[lastValidIndex * 3 + 1];
			const lastZ = pos[lastValidIndex * 3 + 2];
			for (let i = currentPointIndex; i < points; i++) {
				pos[i * 3 + 0] = lastX;
				pos[i * 3 + 1] = lastY;
				pos[i * 3 + 2] = lastZ;
			}

			return pos;
		};

		// Generates a point cloud cylinder using deterministic grid pattern on the side and sunflower pattern on the caps.
		const generateDottedCylinderPositions = (size = SHAPE_SIZE, points = POINT_COUNT) => {
			const radius = size / 2;
			const height = size;
			const halfHeight = height / 2;
			const pos = new Float32Array(points * 3);

			// Distribution targets to hit 1400
			const WALL_TARGET = 1015;
			const P_CAP_1 = 192; // Top Cap
			const P_CAP_2 = 193; // Bottom Cap (1015 + 192 + 193 = 1400)

			let currentPointIndex = 0;

			// 1. Side Wall (Grid based on unwrapped cylinder)
			const wallRows = 35;
			const wallCols = 29;
			const heightStep = height / (wallRows - 1);
			const angleStep = (2 * Math.PI) / wallCols;

			for (let r = 0; r < wallRows; r++) {
				for (let c = 0; c < wallCols; c++) {
					if (currentPointIndex >= WALL_TARGET) break;

					const y = r * heightStep - halfHeight;
					const theta = c * angleStep;

					const x = radius * Math.cos(theta);
					const z = radius * Math.sin(theta);

					pos[currentPointIndex * 3 + 0] = x;
					pos[currentPointIndex * 3 + 1] = y;
					pos[currentPointIndex * 3 + 2] = z;
					currentPointIndex++;
				}
			}

			// 2. Top and Bottom Caps (Deterministic points using Golden Angle/Sunflower pattern)
			const goldenAngle = Math.PI * (3 - Math.sqrt(5));

			// Top Cap (192 points)
			for (let i = 0; i < P_CAP_1; i++) {
				const r = Math.sqrt(i / P_CAP_1) * radius;
				const theta = i * goldenAngle;

				const x = r * Math.cos(theta);
				const z = r * Math.sin(theta);
				const y = halfHeight;

				pos[currentPointIndex * 3 + 0] = x;
				pos[currentPointIndex * 3 + 1] = y;
				pos[currentPointIndex * 3 + 2] = z;
				currentPointIndex++;
			}

			// Bottom Cap (193 points)
			for (let i = 0; i < P_CAP_2; i++) {
				const r = Math.sqrt(i / P_CAP_2) * radius;
				const theta = i * goldenAngle;

				const x = r * Math.cos(theta);
				const z = r * Math.sin(theta);
				const y = -halfHeight;

				pos[currentPointIndex * 3 + 0] = x;
				pos[currentPointIndex * 3 + 1] = y;
				pos[currentPointIndex * 3 + 2] = z;
				currentPointIndex++;
			}

			// Padding (safety check)
			const lastValidIndex = currentPointIndex > 0 ? currentPointIndex - 1 : 0;
			const lastX = pos[lastValidIndex * 3 + 0];
			const lastY = pos[lastValidIndex * 3 + 1];
			const lastZ = pos[lastValidIndex * 3 + 2];
			for (let i = currentPointIndex; i < points; i++) {
				pos[i * 3 + 0] = lastX;
				pos[i * 3 + 1] = lastY;
				pos[i * 3 + 2] = lastZ;
			}

			return pos;
		};

		// Generates a point cloud octahedron using a deterministic triangle grid on each of the 8 faces.
		const generateDottedOctahedronPositions = (size = SHAPE_SIZE, points = POINT_COUNT) => {
			const pos = new Float32Array(points * 3);
			const P_PER_FACE = Math.floor(points / 8); // 175
			const NUM_LINES = 18; // 18 lines gives 171 points per face, total 1368.

			// Vertices scaled to fit size
			const vScale = size / 2;
			const V = [
				new THREE.Vector3(vScale, 0, 0), // 0: +X
				new THREE.Vector3(-vScale, 0, 0), // 1: -X
				new THREE.Vector3(0, vScale, 0), // 2: +Y
				new THREE.Vector3(0, -vScale, 0), // 3: -Y
				new THREE.Vector3(0, 0, vScale), // 4: +Z
				new THREE.Vector3(0, 0, -vScale), // 5: -Z
			];

			// Faces (8 of them) - defined by 3 vertices
			const FACES = [
				[V[2], V[0], V[4]], [V[2], V[4], V[1]], [V[2], V[1], V[5]], [V[2], V[5], V[0]], // Top half
				[V[3], V[4], V[0]], [V[3], V[1], V[4]], [V[3], V[5], V[1]], [V[3], V[0], V[5]], // Bottom half
			];

			let currentPointIndex = 0;

			for (let f = 0; f < 8; f++) {
				// Distribute remainder points (1400 % 8 = 0, but use for robustness)
				const numPoints = P_PER_FACE + (f < (points % 8) ? 1 : 0);
				const [vA, vB, vC] = FACES[f];

				let localPointCount = 0;

				for (let i = 0; i < NUM_LINES; i++) {
					const t = i / (NUM_LINES - 1);

					// Linearly interpolate along two sides
					const vStart = new THREE.Vector3().copy(vA).lerp(vB, t);
					const vEnd = new THREE.Vector3().copy(vA).lerp(vC, t);

					const pointsOnLine = i + 1;
					for (let j = 0; j < pointsOnLine; j++) {
						if (currentPointIndex >= points || localPointCount >= numPoints) break;

						const u = (pointsOnLine > 1) ? j / (pointsOnLine - 1) : 0;

						const p = vStart.clone().lerp(vEnd, u);

						pos[currentPointIndex * 3 + 0] = p.x;
						pos[currentPointIndex * 3 + 1] = p.y;
						pos[currentPointIndex * 3 + 2] = p.z;

						currentPointIndex++;
						localPointCount++;
					}
					if (currentPointIndex >= points || localPointCount >= numPoints) break;
				}
			}

			// Pad remaining points
			const lastValidIndex = currentPointIndex > 0 ? currentPointIndex - 1 : 0;
			const lastX = pos[lastValidIndex * 3 + 0];
			const lastY = pos[lastValidIndex * 3 + 1];
			const lastZ = pos[lastValidIndex * 3 + 2];
			for (let i = currentPointIndex; i < points; i++) {
				pos[i * 3 + 0] = lastX;
				pos[i * 3 + 1] = lastY;
				pos[i * 3 + 2] = lastZ;
			}

			return pos;
		};

		// Generates a point cloud dodecahedron using a deterministic triangle grid on the 60 smaller triangles that make up its 12 pentagonal faces.
		const generateDottedDodecahedronPositions = (size = SHAPE_SIZE, points = POINT_COUNT) => {
			const pos = new Float32Array(points * 3);
			const NUM_TRIANGLES = 60; // Dodecahedron faces (12) * 5 triangles/face
			const P_PER_TRIANGLE = 24; // P_PER_TRIANGLE * NUM_TRIANGLES = 1440 (close enough to 1400)
			const NUM_LINES = 6; // N(N+1)/2 = 21 points per triangle (close to 24)

			// Use Three.js's internal geometry to get the 60 constituent triangles
			const dodecahedronGeometry = new THREE.DodecahedronGeometry(1);
			const faceVertices = dodecahedronGeometry.attributes.position.array;

			// Scale factor to match the desired SHAPE_SIZE
			const maxDist = 1.376; // Max distance from center to vertex for unit dodecahedron (approx)
			const scale = (size / 2) / maxDist;

			let currentPointIndex = 0;

			// Iterate through all 60 triangles (9 values per triangle: x1,y1,z1, x2,y2,z2, x3,y3,z3)
			for (let i = 0; i < faceVertices.length; i += 9) {
				// Define the 3 vertices of the current triangle, scaled
				const vA = new THREE.Vector3(faceVertices[i+0], faceVertices[i+1], faceVertices[i+2]).multiplyScalar(scale);
				const vB = new THREE.Vector3(faceVertices[i+3], faceVertices[i+4], faceVertices[i+5]).multiplyScalar(scale);
				const vC = new THREE.Vector3(faceVertices[i+6], faceVertices[i+7], faceVertices[i+8]).multiplyScalar(scale);

				let localPointCount = 0;
				// Apply the triangle grid method (from one vertex towards the opposite base)
				for (let r = 0; r < NUM_LINES; r++) {
					const t = r / (NUM_LINES - 1);

					// Linearly interpolate along two sides
					const vStart = vA.clone().lerp(vB, t);
					const vEnd = vA.clone().lerp(vC, t);

					const pointsOnLine = r + 1;
					for (let c = 0; c < pointsOnLine; c++) {
						if (currentPointIndex >= points || localPointCount >= P_PER_TRIANGLE) break;

						const u = (pointsOnLine > 1) ? c / (pointsOnLine - 1) : 0;

						const p = vStart.clone().lerp(vEnd, u);

						pos[currentPointIndex * 3 + 0] = p.x;
						pos[currentPointIndex * 3 + 1] = p.y;
						pos[currentPointIndex * 3 + 2] = p.z;

						currentPointIndex++;
						localPointCount++;
					}
				}
			}

			// Pad remaining points
			const lastValidIndex = currentPointIndex > 0 ? currentPointIndex - 1 : 0;
			const lastX = pos[lastValidIndex * 3 + 0];
			const lastY = pos[lastValidIndex * 3 + 1];
			const lastZ = pos[lastValidIndex * 3 + 2];
			for (let i = currentPointIndex; i < points; i++) {
				pos[i * 3 + 0] = lastX;
				pos[i * 3 + 1] = lastY;
				pos[i * 3 + 2] = lastZ;
			}

			return pos;
		};


		// --- Initial Setup and Pre-calculation ---

		// 1. Generate and store all shape positions
		shapePositions['sphere'] = generateDottedSpherePositions();
		shapePositions['cuboid'] = generateDottedCuboidPositions();
		shapePositions['pyramid'] = generateDottedPyramidPositions();
		shapePositions['cylinder'] = generateDottedCylinderPositions();
		shapePositions['octahedron'] = generateDottedOctahedronPositions();
		shapePositions['dodecahedron'] = generateDottedDodecahedronPositions();

		// 2. Setup the single mutable geometry (starts as sphere)
		let currentPositions = shapePositions['sphere'].slice();
		const centralGeometry = new THREE.BufferGeometry();
		const positionAttribute = new THREE.BufferAttribute(currentPositions, 3);
		centralGeometry.setAttribute("position", positionAttribute);

		const centralObject = new THREE.Points(centralGeometry, sharedMaterial);
		group.add(centralObject);

		// Morphing related state
		let sourcePositions = currentPositions;
		let targetPositions = shapePositions['cuboid']; // Prepare for first transition
		let morphStartTime = 0;


		// --- Shape Switching Logic (Initiates Morph) ---
		const startMorph = () => {
			isMorphing = true;
			morphStartTime = performance.now();

			// Advance shape index (cycles through all 6 shapes)
			currentShapeIndex = (currentShapeIndex + 1) % SHAPE_NAMES.length;
			const nextShapeName = SHAPE_NAMES[currentShapeIndex];

			// The source positions are the current positions when the morph starts
			sourcePositions = centralGeometry.attributes.position.array.slice();

			// The target is the pre-calculated position array for the next shape
			targetPositions = shapePositions[nextShapeName];
		};


		// --- Subtle background particle field (retained) ---
		const particlesCount = 700;
		const particlePositions = new Float32Array(particlesCount * 3);
		for (let i = 0; i < particlesCount; i++) {
			const r = 6 + Math.random() * 8;
			const theta = Math.random() * Math.PI * 2;
			const phi = (Math.random() - 0.5) * Math.PI;
			particlePositions[i * 3 + 0] = Math.cos(theta) * Math.cos(phi) * r;
			particlePositions[i * 3 + 1] = Math.sin(phi) * r * 0.6;
			particlePositions[i * 3 + 2] = Math.sin(theta) * Math.cos(phi) * r;
		}
		const pgeo = new THREE.BufferGeometry();
		pgeo.setAttribute("position", new THREE.BufferAttribute(particlePositions, 3));
		const pmat = new THREE.PointsMaterial({
			size: 0.01,
			color: 0x00d4ff,
			transparent: true,
			opacity: 0.08,
			depthTest: false,
			blending: THREE.AdditiveBlending,
		});
		const backgroundParticles = new THREE.Points(pgeo, pmat);
		scene.add(backgroundParticles);

		// --- Fusing Particle Setup ---
		const FUSING_PARTICLE_COLOR = 0x00ffaa; // Marine green/cyan
		const MAX_FUSING_PARTICLES = 30;
		const FUSION_SPEED = 0.005; // Base speed for movement
		const FUSION_THRESHOLD = 0.5; // Distance to center to be considered fused
		const PARTICLE_SPAWN_INTERVAL = 500; // Average spawn every 0.5 seconds

		// Array to hold the state of each fusing particle {x, y, z}
		let fusingParticles = []; 
		const fusingParticlePositions = new Float32Array(MAX_FUSING_PARTICLES * 3);
		
		const fusingGeo = new THREE.BufferGeometry();
		fusingGeo.setAttribute("position", new THREE.BufferAttribute(fusingParticlePositions, 3));
		
		const fusingMat = new THREE.PointsMaterial({
			size: 0.035, // Larger and brighter pixel
			color: FUSING_PARTICLE_COLOR,
			transparent: true,
			opacity: 1.0,
			blending: THREE.AdditiveBlending,
			depthTest: false,
			sizeAttenuation: true,
		});
		
		const fusingParticlesObject = new THREE.Points(fusingGeo, fusingMat);
		scene.add(fusingParticlesObject);
		
		let lastParticleSpawnTime = 0;
		
		const spawnFusingParticle = () => {
			if (fusingParticles.length >= MAX_FUSING_PARTICLES) return;

			// Randomly select a spawning edge far outside the center view (camera is at z=4.5)
			const spawnDistance = 15;
			const pos = new THREE.Vector3();

			// Randomly pick a starting face (6 faces of a large box)
			const face = Math.floor(Math.random() * 6);
			switch (face) {
				case 0: // +X
					pos.set(spawnDistance, (Math.random() - 0.5) * spawnDistance, (Math.random() - 0.5) * spawnDistance);
					break;
				case 1: // -X
					pos.set(-spawnDistance, (Math.random() - 0.5) * spawnDistance, (Math.random() - 0.5) * spawnDistance);
					break;
				case 2: // +Y (Top)
					pos.set((Math.random() - 0.5) * spawnDistance, spawnDistance, (Math.random() - 0.5) * spawnDistance);
					break;
				case 3: // -Y (Bottom)
					pos.set((Math.random() - 0.5) * spawnDistance, -spawnDistance, (Math.random() - 0.5) * spawnDistance);
					break;
				case 4: // +Z (Behind)
					pos.set((Math.random() - 0.5) * spawnDistance, (Math.random() - 0.5) * spawnDistance, spawnDistance);
					break;
				case 5: // -Z (In front of camera)
					pos.set((Math.random() - 0.5) * spawnDistance, (Math.random() - 0.5) * spawnDistance, -spawnDistance);
					break;
			}
			
			// Target is the origin of the morphing group (0, 0, 0)
			fusingParticles.push({
				x: pos.x, y: pos.y, z: pos.z,
			});
		};


		// Animation loop
		let start = performance.now();
		lastSwitchTime = start; // Start the first hold time immediately

		let rafId = null;

		const loop = (now) => {
			const elapsed = (now - start) / 1000;

			// --- Morphing Logic ---
			if (isMorphing) {
				const timeElapsed = now - morphStartTime;
				let progress = Math.min(1, timeElapsed / TRANSITION_DURATION);

				// Use a smooth step function for easing the transition
				const smoothProgress = progress * progress * (3 - 2 * progress);

				// Interpolate point positions
				for (let i = 0; i < POINT_COUNT * 3; i++) {
					currentPositions[i] = sourcePositions[i] +
										(targetPositions[i] - sourcePositions[i]) * smoothProgress;
				}
				positionAttribute.needsUpdate = true; // Tell Three.js the buffer needs updating

				if (progress >= 1) {
					isMorphing = false;
					lastSwitchTime = now; // Reset timer for the hold duration
				}

			} else {
				// Check if hold duration is over, then start the next morph
				if (now - lastSwitchTime > HOLD_DURATION) {
					startMorph();
				}
			}

			// --- Central Shape Color Cycle ---
			const colorCycleSpeed = 0.15;
			const hue = (elapsed * colorCycleSpeed) % 1;
			sharedMaterial.color.setHSL(hue, 1.0, 0.55);

			// --- Fusing Particle Logic (Spawn & Move) ---
			// Spawn logic: Randomize the interval slightly around the target
			if (now - lastParticleSpawnTime > PARTICLE_SPAWN_INTERVAL * (0.5 + Math.random() * 1.5)) {
				spawnFusingParticle();
				lastParticleSpawnTime = now;
			}
			
			let activeParticleCount = 0;
			const newFusingParticles = [];
			const targetVector = new THREE.Vector3(0, 0, 0);

			for (let i = 0; i < fusingParticles.length; i++) {
				const p = fusingParticles[i];
				const currentPos = new THREE.Vector3(p.x, p.y, p.z);
				
				// Calculate direction vector towards target (0,0,0)
				const direction = targetVector.clone().sub(currentPos).normalize();
				
				// Check distance to fusion threshold
				const distance = currentPos.distanceTo(targetVector);
				
				if (distance > FUSION_THRESHOLD) {
					// Move particle with speed proportional to distance (slowing down as it approaches)
					const speed = FUSION_SPEED * distance;

					p.x += direction.x * speed; 
					p.y += direction.y * speed; 
					p.z += direction.z * speed;

					// Update buffer position
					fusingParticlePositions[activeParticleCount * 3 + 0] = p.x;
					fusingParticlePositions[activeParticleCount * 3 + 1] = p.y;
					fusingParticlePositions[activeParticleCount * 3 + 2] = p.z;
					
					newFusingParticles.push(p);
					activeParticleCount++;
				} 
				// Else: Particle has fused, it is dropped from newFusingParticles array
			}
			
			fusingParticles = newFusingParticles; // Update list of active particles
			
			// Hide unused buffer positions (by setting draw range and leaving positions undefined)
			fusingGeo.attributes.position.needsUpdate = true; // Mark buffer for update
			fusingGeo.setDrawRange(0, activeParticleCount); // Only draw active particles


			// Rotate entire group for subtle dynamic parallax
			group.rotation.y = Math.sin(elapsed * 0.12) * 0.12;
			group.rotation.x = Math.cos(elapsed * 0.06) * 0.04;

			// Shape rotation (applies to the central object regardless of current shape)
			centralObject.rotation.y += 0.0025;
			centralObject.rotation.x += 0.0012;

			// Background particles rotate slowly for depth
			backgroundParticles.rotation.y += 0.0009;

			renderer.render(scene, camera);
			rafId = requestAnimationFrame(loop);
		};

		requestAnimationFrame(loop);

		// Resize handling
		const onResize = () => {
			renderer.setSize(window.innerWidth, window.innerHeight);
			camera.aspect = window.innerWidth / window.innerHeight;
			camera.updateProjectionMatrix();
		};
		window.addEventListener("resize", onResize);

		// Cleanup
		return () => {
			window.removeEventListener("resize", onResize);
			if (rafId) cancelAnimationFrame(rafId);
			try {
				centralGeometry.dispose();
				sharedMaterial.dispose();
				pgeo.dispose();
				pmat.dispose();
				fusingGeo.dispose();
				fusingMat.dispose();
				renderer.dispose();
			} catch (e) {
				console.error("Error disposing Three.js resources:", e);
			}
		};
	}, []);

	// UI - preserved theme look (frosted cards, gradient blue buttons)
	return (
		<>
			{/* Tailwind CSS is assumed. Custom CSS for aesthetics and layout is provided in a style tag. */}
			<style>{`
:root{--primary-blue:#0066ff;--secondary-cyan:#00d4ff;--accent-green:#00ff88;--deep-ocean:#001133;--dark-blue:#002266;--glass-border:rgba(255,255,255,0.08);--text-primary:#ffffff;--text-muted:#9acfff;--gradient-primary:linear-gradient(135deg,var(--primary-blue) 0%,var(--secondary-cyan) 100%);--gradient-bg:radial-gradient(ellipse at center,var(--dark-blue) 0%,var(--deep-ocean) 100%)}
*{box-sizing:border-box}html,body,#root{height:100%;width:100%}body{margin:0;font-family:'Inter',system-ui,Roboto;color:var(--text-primary);background:var(--gradient-bg);overflow:hidden}
#selector-bg-canvas{position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:0;pointer-events:none}

/* UPDATED CONTAINER: Removed justify-content and added flex: 1 wrapper for centering */
.container{position:relative;z-index:10;height:100vh;padding:2rem 3rem;display:flex;flex-direction:column;align-items:center}
/* NEW: Wrapper to take up remaining vertical space and center the cards */
.main-content-area{
	flex: 1; 
	width: 100%;
	display: flex;
	justify-content: center; /* Center cards horizontally */
	align-items: center; /* Center cards vertically */
	min-height: 0;
}

.header{text-align:center;margin-bottom:30px; margin-top: 30px;}
.header .logo{font-size:clamp(2rem,4vw,3.5rem);font-weight:800;background:var(--gradient-primary);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.header .subtitle{color:var(--text-muted);margin-top:8px;font-size:1.1rem}

/* UPDATED ROW: Increased gap and max-width for aesthetic horizontal spread */
.selector-row{
    display:flex;
    gap:4rem;
    align-items:stretch;
    width:100%;
    max-width:1600px;
    padding:0 50px;
    justify-content:space-between;
    /* ADDED: Vertical shift up by 10% of viewport height (approx 10-15%) */
    transform: translateY(-10vh);
}
/* UPDATED CARD: Increased size (width and padding/height) */
.selection-card{
	flex:1;
	min-width:350px; /* Wider minimum width */
	max-width:550px; /* Wider maximum width */
	background:rgba(255,255,255,0.04);
	border-radius:18px;
	padding:50px 40px; /* Increased vertical padding for taller look */
	backdrop-filter:blur(12px);
	border:1px solid var(--glass-border);
	box-shadow:0 18px 60px rgba(0,17,51,0.5);
	display:flex;
	flex-direction:column;
	align-items:center;
	transition:transform .2s,box-shadow .2s
}
.selection-card:hover{transform:translateY(-10px);box-shadow:0 35px 90px rgba(0,17,51,0.7)}
/* Increased icon size and spacing */
.selection-icon{width:90px;height:90px;border-radius:999px;background:linear-gradient(180deg, rgba(0,212,255,0.15), rgba(0,102,255,0.18));display:flex;align-items:center;justify-content:center;font-size:45px;box-shadow:0 12px 35px rgba(0,102,255,0.15); margin-bottom: 25px;}
/* Increased title size and spacing */
.selection-title{font-weight:700;color:var(--text-primary);text-align:center;font-size:1.5rem; margin-bottom: 12px;}
/* Increased description spacing */
.selection-desc{color:var(--text-muted);font-size:1.05rem;text-align:center;margin-bottom:30px}
/* KEY FIX: margin-top: auto pushes the button to the bottom edge of the card, and increased size */
.select-btn{width:100%;padding:16px 20px;border-radius:14px;border:none;font-weight:800;background:var(--gradient-primary);color:white;cursor:pointer;box-shadow:0 12px 35px rgba(0,102,255,0.35);font-size:1.2rem;margin-top: auto;}
.select-btn:hover{transform:translateY(-3px)}
.center-glow{position:absolute;left:50%;transform:translateX(-50%);top:calc(50% - 8px);z-index:5;pointer-events:none}
@media(max-width:1024px){.selector-row{gap:2rem}.selection-card{min-width:280px}} /* Slightly reduced gap on medium screens */
@media(max-width:768px){.container{height:auto;min-height:100vh;padding-top:40px;padding-bottom:40px} /* Allow scrolling on mobile */
/* Reset transform on mobile */
.selector-row{flex-direction:column;align-items:center;padding:0 18px;gap:20px; transform: none;}.selection-card{width:100%;max-width:400px}}
`}</style>

			<canvas id="selector-bg-canvas" ref={canvasRef} />

			<div className="container">
				<header className="header">
					<div className="logo">Select Your Stakeholder Dashboard</div>
					<div className="subtitle">Choose the role that matches your profile:</div>
				</header>

				{/* Wrapper to center the card row */}
				<div className="main-content-area">
					<div className="selector-row" role="list">
						<div className="selection-card" role="listitem">
							<div className="selection-icon">🔬</div>
							<div className="selection-title">Researcher / Scientist</div>
							<div className="selection-desc">View species analysis & novel findings</div>
							<button className="select-btn" onClick={() => onSelect("researcher")}>SELECT</button>
						</div>

						<div className="selection-card" role="listitem">
							<div className="selection-icon">🏛️</div>
							<div className="selection-title">Policymaker / Government</div>
							<div className="selection-desc">View regional biodiversity & policy data</div>
							<button className="select-btn" onClick={() => onSelect("policymaker")}>SELECT</button>
						</div>

						<div className="selection-card" role="listitem">
							<div className="selection-icon">🏭</div>
							<div className="selection-title">Industry / Biotech</div>
							<div className="selection-desc">View legal compliance & metrics</div>
							<button className="select-btn" onClick={() => onSelect("industry")}>SELECT</button>
						</div>
					</div>
				</div>
			</div>
		</>
	);
}
