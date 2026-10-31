import { useEffect, useMemo, useRef } from 'react';
import { Canvas, useFrame, useLoader, useThree } from '@react-three/fiber';
import { onFrame } from '../lib/frameClock';
import { ShaderMaterial, TextureLoader, Vector3, SRGBColorSpace, type Mesh } from 'three';

const REVOLUTION_SECONDS = 150;
// One turn takes 150 s, so 15 frames a second looks identical to 60 and costs a quarter of the GPU. Frames are also skipped while the page is
// scrolling, hidden or the planet is off screen: the planet must never compete with the interface for the GPU.

// Monochrome planet: near-black ocean, grey continents from NASA imagery, light from the upper right, thin bright limb.
const vertex = /* glsl */ `
varying vec2 vUv; varying vec3 vN; varying vec3 vV;
void main() {
  vUv = uv; vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz);
  gl_Position = projectionMatrix * mv;
}`;
const fragment = /* glsl */ `
uniform sampler2D map; uniform vec3 sun;
varying vec2 vUv; varying vec3 vN; varying vec3 vV;
void main() {
  vec3 c = texture2D(map, vUv).rgb;
  float luma = dot(c, vec3(0.299, 0.587, 0.114));
  // land = not blue-dominant (ocean and shallows), plus bright ice
  float dry = (c.r + c.g) * 0.5 - c.b;
  float land = max(smoothstep(0.02, 0.12, dry), smoothstep(0.55, 0.8, luma));
  float surface = mix(0.012, 0.05 + 0.42 * luma, land);
  float nd = dot(normalize(vN), normalize(sun));
  float lit = 0.30 + 0.70 * smoothstep(-0.1, 0.9, nd);
  float rim = pow(1.0 - max(dot(normalize(vN), normalize(vV)), 0.0), 2.8);
  float rimLit = rim * smoothstep(-0.1, 0.7, nd);
  vec3 col = vec3(surface * lit) + vec3(rimLit * 0.9) + vec3(rim * 0.025);
  gl_FragColor = vec4(col, 1.0);
}`;

function Planet({ animate, lowPower }: { animate: boolean; lowPower: boolean }) {
  const mesh = useRef<Mesh>(null);
  const texture = useLoader(TextureLoader, `${import.meta.env.BASE_URL}earth.jpg`);
  texture.colorSpace = SRGBColorSpace;
  texture.anisotropy = lowPower ? 1 : 4;
  const material = useMemo(() => new ShaderMaterial({
    vertexShader: vertex, fragmentShader: fragment,
    uniforms: { map: { value: texture }, sun: { value: new Vector3(0.95, 0.4, 0.15) } },
  }), [texture]);
  useEffect(() => () => material.dispose(), [material]);
  // delta-based: the same speed at any frame rate; one turn per REVOLUTION_SECONDS.
  useFrame((_, delta) => { if (animate && mesh.current) mesh.current.rotation.y += delta * (Math.PI * 2) / REVOLUTION_SECONDS; });
  return <mesh ref={mesh} rotation={[0.35, 2.2, 0.1]} material={material}><sphereGeometry args={[1, lowPower ? 48 : 96, lowPower ? 36 : 72]} /></mesh>;
}

/** Asks for a new frame on the shared frame clock (15 a second, together with the orbs; none while scrolling or hidden), when the planet is on screen. */
function Pacer({ active, visible }: { active: boolean; visible: React.MutableRefObject<boolean> }) {
  const invalidate = useThree(s => s.invalidate);
  useEffect(() => (active ? onFrame(() => { if (visible.current) invalidate(); }) : undefined), [active, invalidate, visible]);
  return null;
}

export default function Globe({ animate, lowPower }: { animate: boolean; lowPower: boolean }) {
  const wrap = useRef<HTMLDivElement>(null);
  const visible = useRef(true);
  useEffect(() => {
    const el = wrap.current; if (!el) return;
    const io = new IntersectionObserver(([e]) => { visible.current = e.isIntersecting; }, { threshold: 0 });
    io.observe(el); return () => io.disconnect();
  }, []);
  const running = animate && typeof document !== 'undefined' && document.visibilityState === 'visible';
  return (
    <div ref={wrap} className="globe-frame">
      <Canvas dpr={lowPower ? 1 : [1, 1.25]} frameloop="demand" camera={{ position: [0, 0, 4], fov: 34 }}
              gl={{ antialias: !lowPower, alpha: true, powerPreference: lowPower ? 'low-power' : 'default' }} style={{ pointerEvents: 'none' }}>
        <Pacer active={running} visible={visible} />
        <Planet animate={running} lowPower={lowPower} />
      </Canvas>
    </div>
  );
}
