import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const settings = vi.hoisted(() => ({ reducedMotion: false }));
vi.mock('../state/settings', () => ({ useSettings: () => settings }));
vi.mock('../lib/api', () => ({ api: vi.fn(async (_m: string, path: string) => (path.includes('presence') ? { state: 'asleep' } : { events: [] })) }));
import SceneBackground from './SceneBackground';

describe('SceneBackground', () => {
  it('shows a still picture of the scene when motion is reduced', async () => {
    settings.reducedMotion = true;
    const { container } = render(<SceneBackground task={undefined} ready />);
    expect(container.querySelector('video')).toBeNull();
    expect(container.querySelector('img.scene-poster')?.getAttribute('src')).toMatch(/scenes\/idle\.jpg$/);
    expect(container.querySelector('.scene')?.getAttribute('aria-hidden')).toBe('true');
  });
  it('is decorative: it plays muted videos hidden from assistive technology', () => {
    settings.reducedMotion = false;
    HTMLMediaElement.prototype.load = vi.fn();
    HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve());
    const { container } = render(<SceneBackground task={undefined} ready={false} />);
    const videos = container.querySelectorAll('video');
    expect(videos).toHaveLength(2);
    videos.forEach(v => { expect(v.muted).toBe(true); expect(v.getAttribute('tabindex')).toBe('-1'); });
    expect(screen.queryByRole('img')).toBeNull();
  });
});
