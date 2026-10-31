import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
/** Only embedded GLB resources are accepted. External model URLs and textures are blocked. */
export default function Model({ src, label }: { src: string; label: string }) {
  const mount = useRef<HTMLDivElement>(null); const [error, setError] = useState('');
  useEffect(() => {
    const root = mount.current!; let renderer: THREE.WebGLRenderer | undefined, scene: THREE.Scene | undefined, controls: OrbitControls | undefined; const controller = new AbortController(); let dead = false;
    (async () => {
      try {
        const response = await fetch(src, { credentials: 'same-origin', signal: controller.signal }); if (!response.ok) throw new Error('File unavailable.');
        const buffer = await response.arrayBuffer(); if (new DataView(buffer).getUint32(0, true) !== 0x46546c67) throw new Error('Only binary GLB models are supported.');
        const manager = new THREE.LoadingManager(); manager.setURLModifier(url => { if (!url.startsWith('blob:') && !url.startsWith('data:image/')) throw new Error('External model resources are blocked.'); return url; });
        const model = await new GLTFLoader(manager).parseAsync(buffer, ''); if (dead) return;
        scene = new THREE.Scene(); scene.add(model.scene, new THREE.HemisphereLight(0xffffff, 0x444444, 3));
        const box = new THREE.Box3().setFromObject(model.scene), size = box.getSize(new THREE.Vector3()).length() || 1, center = box.getCenter(new THREE.Vector3()); model.scene.position.sub(center);
        const camera = new THREE.PerspectiveCamera(40, 1.5, size / 100, size * 100); camera.position.set(size, size * .5, size * 1.5);
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); renderer.setSize(root.clientWidth || 600, 320); camera.aspect = (root.clientWidth || 600) / 320; camera.updateProjectionMatrix(); root.appendChild(renderer.domElement);
        controls = new OrbitControls(camera, renderer.domElement); controls.addEventListener('change', () => renderer?.render(scene!, camera)); renderer.render(scene, camera);
      } catch (e) { if (!dead) setError((e as Error).message); }
    })();
    return () => { dead = true; controller.abort(); controls?.dispose(); scene?.traverse(o => { const m = o as THREE.Mesh; m.geometry?.dispose(); const materials = Array.isArray(m.material) ? m.material : [m.material]; materials.filter(Boolean).forEach(mat => mat.dispose()); }); renderer?.dispose(); root.replaceChildren(); };
  }, [src]);
  return <div>{error ? <p role="alert">{error}</p> : <><div ref={mount} className="gen-model" role="img" aria-label={label} /><p className="faint">Drag to orbit; scroll to zoom. {label}</p></>}</div>;
}
