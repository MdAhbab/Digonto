import { useEffect, useRef } from "react";
import * as THREE from "three";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

/* A real Three.js Earth built from a point-cloud globe + atmosphere rim.
   No external textures (works offline). GSAP ScrollTrigger scrubs the camera
   from deep space down toward Dhaka as the hero scrolls, then hands off to
   the rest of the page. Fully teardown-safe and reduced-motion aware. */
export function EarthScene({ theme }: { theme: "light" | "dark" }) {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const isDark = theme === "dark";

    const accent = new THREE.Color(isDark ? "#4ba38c" : "#0f3d33");
    const gold = new THREE.Color(isDark ? "#cba85c" : "#9a7b32");
    const dot = new THREE.Color(isDark ? "#8fd8c4" : "#0f3d33");

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, mount.clientWidth / mount.clientHeight, 0.1, 100);
    camera.position.set(0, 0, 3.4);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    const globe = new THREE.Group();
    scene.add(globe);

    const RADIUS = 1;

    // ---- point-cloud sphere (fibonacci distribution) ----
    const COUNT = 7000;
    const positions = new Float32Array(COUNT * 3);
    const phi = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < COUNT; i++) {
      const y = 1 - (i / (COUNT - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      const theta = phi * i;
      positions[i * 3] = Math.cos(theta) * r * RADIUS;
      positions[i * 3 + 1] = y * RADIUS;
      positions[i * 3 + 2] = Math.sin(theta) * r * RADIUS;
    }
    const ptGeo = new THREE.BufferGeometry();
    ptGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const ptMat = new THREE.PointsMaterial({
      color: dot,
      size: 0.012,
      transparent: true,
      opacity: isDark ? 0.9 : 0.55,
      sizeAttenuation: true,
    });
    globe.add(new THREE.Points(ptGeo, ptMat));

    // ---- faint wireframe sphere for structure ----
    const wire = new THREE.LineSegments(
      new THREE.WireframeGeometry(new THREE.SphereGeometry(RADIUS * 0.995, 36, 24)),
      new THREE.LineBasicMaterial({ color: accent, transparent: true, opacity: isDark ? 0.1 : 0.08 }),
    );
    globe.add(wire);

    // ---- inner solid sphere to occlude back points ----
    const core = new THREE.Mesh(
      new THREE.SphereGeometry(RADIUS * 0.96, 48, 48),
      new THREE.MeshBasicMaterial({ color: new THREE.Color(isDark ? "#08110d" : "#e9e5db") }),
    );
    globe.add(core);

    // ---- atmosphere rim (fresnel) ----
    // Dark mode: additive glow reads as a luminous halo. Light mode: additive on
    // pale paper just muddies to grey, so use a soft sage rim with normal blending.
    const atmoColor = isDark ? accent : new THREE.Color("#7ba694");
    const atmoStrength = isDark ? 0.9 : 0.55;
    const atmoMat = new THREE.ShaderMaterial({
      uniforms: { uColor: { value: atmoColor }, uStrength: { value: atmoStrength } },
      vertexShader: `
        varying vec3 vN;
        void main(){
          vN = normalize(normalMatrix * normal);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0);
        }`,
      fragmentShader: `
        varying vec3 vN;
        uniform vec3 uColor;
        uniform float uStrength;
        void main(){
          float i = pow(1.0 - abs(vN.z), 3.0);
          gl_FragColor = vec4(uColor, i * uStrength);
        }`,
      transparent: true,
      blending: isDark ? THREE.AdditiveBlending : THREE.NormalBlending,
      side: THREE.BackSide,
      depthWrite: false,
    });
    const atmo = new THREE.Mesh(new THREE.SphereGeometry(RADIUS * 1.18, 48, 48), atmoMat);
    globe.add(atmo);

    // ---- Dhaka marker + pulse ----
    const latLngToVec = (lat: number, lng: number, r: number) => {
      const p = (90 - lat) * (Math.PI / 180);
      const t = (lng + 180) * (Math.PI / 180);
      return new THREE.Vector3(
        -r * Math.sin(p) * Math.cos(t),
        r * Math.cos(p),
        r * Math.sin(p) * Math.sin(t),
      );
    };
    const dhaka = latLngToVec(23.81, 90.41, RADIUS * 1.01);
    const marker = new THREE.Mesh(
      new THREE.SphereGeometry(0.02, 16, 16),
      new THREE.MeshBasicMaterial({ color: gold }),
    );
    marker.position.copy(dhaka);
    globe.add(marker);
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.03, 0.045, 32),
      new THREE.MeshBasicMaterial({ color: gold, transparent: true, opacity: 0.6, side: THREE.DoubleSide }),
    );
    ring.position.copy(dhaka);
    ring.lookAt(dhaka.clone().multiplyScalar(2));
    globe.add(ring);

    // stars
    const starCount = 600;
    const starPos = new Float32Array(starCount * 3);
    for (let i = 0; i < starCount; i++) {
      const v = new THREE.Vector3().randomDirection().multiplyScalar(THREE.MathUtils.randFloat(6, 14));
      starPos[i * 3] = v.x; starPos[i * 3 + 1] = v.y; starPos[i * 3 + 2] = v.z;
    }
    const starGeo = new THREE.BufferGeometry();
    starGeo.setAttribute("position", new THREE.BufferAttribute(starPos, 3));
    const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({ color: gold, size: 0.03, transparent: true, opacity: isDark ? 0.5 : 0.25 }));
    scene.add(stars);

    // orient so Dhaka faces the camera initially
    globe.rotation.y = -Math.PI * 0.52;
    globe.rotation.x = 0.35;

    // ---- scroll-driven camera zoom ----
    const state = { zoom: 0 }; // 0 = far, 1 = close
    let st: ScrollTrigger | null = null;
    if (!reduce) {
      st = ScrollTrigger.create({
        trigger: "#earth-stage",
        start: "top top",
        end: "bottom bottom",
        scrub: 1,
        onUpdate: (self) => { state.zoom = self.progress; },
      });
    }

    let raf = 0;
    const clock = new THREE.Clock();
    const render = () => {
      const t = clock.getElapsedTime();
      if (!reduce) globe.rotation.y += 0.0006;
      // ease camera from 3.4 (space) to 1.55 (close on Dhaka)
      const z = 3.4 - state.zoom * 1.85;
      camera.position.z += (z - camera.position.z) * 0.08;
      // subtle tilt toward Dhaka as we approach
      globe.rotation.x += (0.35 - state.zoom * 0.25 - globe.rotation.x) * 0.05;
      const pulse = 1 + Math.sin(t * 2.2) * 0.25;
      ring.scale.setScalar(pulse);
      (ring.material as THREE.MeshBasicMaterial).opacity = 0.6 * (1 - (pulse - 1) / 0.25 * 0.4);
      renderer.render(scene, camera);
      raf = requestAnimationFrame(render);
    };
    render();

    const onResize = () => {
      if (!mount) return;
      camera.aspect = mount.clientWidth / mount.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(mount.clientWidth, mount.clientHeight);
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      st?.kill();
      renderer.dispose();
      ptGeo.dispose();
      if (mount.contains(renderer.domElement)) mount.removeChild(renderer.domElement);
    };
  }, [theme]);

  return <div ref={mountRef} className="h-full w-full" aria-hidden />;
}
