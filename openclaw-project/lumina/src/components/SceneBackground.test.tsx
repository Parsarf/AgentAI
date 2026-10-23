import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const settings = vi.hoisted(() => ({ reducedMotion: false }));
vi.mock('../state/settings', () => ({ useSettings: () => settings }));
vi.mock('../lib/api', () => ({ api: vi.fn(async (_m: string, path: string) => (path.includes('presence') ? { state: 'asleep' } : { events: [] })) }));
import SceneBackground from './SceneBackground';

describe('SceneBackground', () => {
  it('lets the film be paused, and remembers it', async () => {
    settings.reducedMotion = false; localStorage.removeItem('lumina.filmPaused');
    HTMLMediaElement.prototype.load = vi.fn(); HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve());
    const { container } = render(<SceneBackground task={undefined} ready />);
    const button = screen.getByRole('button', { name: 'Pause animation' });
    expect(button.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(button);
    expect(screen.getByRole('button', { name: 'Play animation' }).getAttribute('aria-pressed')).toBe('true');
    expect(container.querySelector('video')).toBeNull();
    expect(localStorage.getItem('lumina.filmPaused')).toBe('1');
    localStorage.removeItem('lumina.filmPaused');
  });
  it('has no pause button when motion is already reduced', () => {
    settings.reducedMotion = true;
    render(<SceneBackground task={undefined} ready />);
    expect(screen.queryByRole('button', { name: /animation/ })).toBeNull();
  });
  it('shows a still picture of the scene when motion is reduced', async () => {
    settings.reducedMotion = true;
    const slot = document.createElement('div'); document.body.appendChild(slot);
    const { container } = render(<SceneBackground task={undefined} ready statusEl={slot} />);
    expect(container.querySelector('video')).toBeNull();
    expect(container.querySelector('img.scene-poster')?.getAttribute('src')).toMatch(/scenes\/idle\.jpg$/);
    expect(container.querySelector('.scene-art')?.getAttribute('aria-hidden')).toBe('true');
    expect(slot.querySelector('.thread-status-line')?.textContent).toBe('Ready when you are.');
    slot.remove();
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
