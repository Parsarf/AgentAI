import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import TaskStrip from './TaskStrip';
import { Timeline } from './parts';
import { troubleLine, waitLine } from '../../lib/work';
import { hold, resetWork, row, summary, view, work } from '../../test/workMock';
vi.mock('../../state/work', async () => (await import('../../test/workMock')).mock);
vi.mock('../Orb', () => ({ default: () => <span data-testid="orb" /> }));
vi.mock('../../lib/api', async importOriginal => ({ ...await importOriginal<object>(), api: vi.fn(async () => ({})) }));

const strip = (id = 'r1') => render(<MemoryRouter><TaskStrip id={id} /></MemoryRouter>);
const seconds = () => Math.floor(Date.now() / 1000);
beforeEach(() => resetWork());
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('a wait the server named', () => {
  it('says what the task is waiting for and how long it has been, in measured time', () => {
    work.tasks = [summary({ label: 'Waiting for the model', waiting_for: 'model', since_epoch: seconds() - 25 })];
    strip();
    expect(screen.getByText('Waiting for the model…')).toBeTruthy();
    expect(screen.getByText(/^2[5-7]s so far$/)).toBeTruthy();
  });
  it('says nothing about time for the first seconds, when there is nothing to explain yet', () => {
    expect(waitLine({ waiting_for: 'model', since_epoch: 1000, expect_seconds: null }, 1004_000)).toBe('');
    expect(waitLine({ waiting_for: 'model', since_epoch: 1000, expect_seconds: null }, 1090_000)).toBe('1m 30s so far');
    expect(waitLine({ waiting_for: null, since_epoch: 1000, expect_seconds: null }, 1090_000)).toBe('');
  });
  it('gives the server\'s own figure for a workspace that is waking, and none when the server has none', () => {
    work.tasks = [summary({ state: 'waiting', phase: 'queued', tone: 'pending', label: 'Waking your workspace', wait: 'assistant', ahead: 0, waiting_for: 'workspace', since_epoch: seconds() - 5, expect_seconds: 95 })];
    strip();
    expect(screen.getByText('Waking your workspace…')).toBeTruthy();
    expect(screen.getByText('Its workspace is starting up. This usually takes about 1m 35s.')).toBeTruthy();
    expect(screen.queryByText('Getting your assistant ready.')).toBeNull();                      // one line about the wait, not two
    expect(waitLine({ waiting_for: 'workspace', since_epoch: 1, expect_seconds: null }, 9_000)).toBe('Its workspace is starting up.');
  });
  it('says a pause the model provider asked for is a pause, and that nothing is needed', () => {
    expect(waitLine({ waiting_for: 'provider', since_epoch: 1, expect_seconds: 21 }, 9_000)).toBe('It asked for a pause of about 21s. The task carries on by itself.');
    expect(waitLine({ waiting_for: 'provider', since_epoch: 1, expect_seconds: null }, 9_000)).toBe('It asked for a short pause. The task carries on by itself.');
  });
  it('says the answer is being written while its text arrives and no tool runs', () => {
    work.tasks = [summary({ label: 'Waiting for the model', waiting_for: 'model', since_epoch: seconds() - 40 })];
    work.drafts = { r1: { item: 'm1', text: 'The cheapest is', done: false, at: Date.now() } };
    strip();
    expect(screen.getByText('Writing the answer…')).toBeTruthy();
    expect(screen.queryByText(/so far$/)).toBeNull();
    cleanup();
    work.tasks = [summary({ label: 'Reading a page', activity: { key: 'c1', category: 'read', label: 'Reading a page', detail: 'example.com' }, now: [{ key: 'c1', category: 'read', label: 'Reading a page', detail: 'example.com' }] })];
    strip();
    expect(screen.getByText('Reading a page…')).toBeTruthy();                                    // a tool that is running is what is happening, whatever was drafted before
  });
});

describe('what the browser did', () => {
  it('lists a call\'s steps under it in the server\'s words, and a failed one stands out by more than colour', () => {
    render(<Timeline live={false} rows={[
      row({ key: 'b1', category: 'browse', label: 'Used the browser', detail: 'shop.example', steps: [
        { label: 'Opened https://shop.example/', status: 'done', at: 1 }, { label: 'Could not click “Expand Men”: something on the page was covering it', status: 'failed', at: 2 },
        { label: 'Clicked “Men”', status: 'done', at: 3 }] }),
      row({ key: 'b2', category: 'browse', label: 'Clicked “Price: High to Low”', detail: 'shop.example', steps: [] })]} />);
    const steps = screen.getByRole('list', { name: 'Steps in the browser' });
    expect(Array.from(steps.querySelectorAll('li')).map(li => li.textContent)).toEqual(['Opened https://shop.example/', 'Could not click “Expand Men”: something on the page was covering it', 'Clicked “Men”']);
    expect(steps.querySelectorAll('li.failed').length).toBe(1);
    expect(screen.getByText('Clicked “Price: High to Low”')).toBeTruthy();
    expect(screen.getAllByRole('list', { name: 'Steps in the browser' }).length).toBe(1);        // a call of one step is that step: no list under it
  });
});

describe('a finished task that had trouble', () => {
  it('says how many steps nothing made up for, with the reason', () => {
    hold(view({ state: 'completed', phase: 'ended', label: 'Done', tone: 'ok', outcome: 'completed', verification: 'not_applicable', steps: 3,
      trouble: { steps: 1, why: 'The assistant asked for something that is not there (a file, a message or an item). Nothing was changed.' } }));
    strip();
    expect(screen.getByText('1 step did not work: The assistant asked for something that is not there (a file, a message or an item). Nothing was changed.')).toBeTruthy();
    expect(troubleLine({ steps: 2, why: '' })).toBe('2 steps did not work.');
  });
  it('says nothing more when every failure was made up for', () => {
    hold(view({ state: 'completed', phase: 'ended', label: 'Done', tone: 'ok', outcome: 'completed', verification: 'not_applicable', steps: 3 }));
    strip();
    expect(document.querySelector('.wk-trouble')).toBeNull();
  });
});
