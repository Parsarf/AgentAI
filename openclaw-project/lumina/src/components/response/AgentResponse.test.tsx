import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import AgentResponse from './AgentResponse';
afterEach(cleanup);
describe('formatted agent answers', () => {
  it('renders the reported toothbrush answer without raw Markdown markers', () => {
    render(<AgentResponse content={'## Best Overall Value: **Oral-B iO Series 3** – ~$70\n\n**Why it wins on value:** This is the standout pick.\n- Smart pressure sensor\n- 3 cleaning modes\n\n## Best Budget Pick: **Philips Sonicare 4100** – $40–50'} />);
    expect(screen.getAllByRole('heading').length).toBe(2);
    expect(screen.getByText('Why it wins on value:').tagName).toBe('STRONG');
    expect(screen.getAllByRole('listitem').length).toBe(2);
    expect(document.body.textContent).not.toContain('##');
    expect(document.body.textContent).not.toContain('**');
  });
  it('renders tables and both explicit and legacy source links', () => {
    render(<AgentResponse content={'| Item | Price |\n| --- | --- |\n| Brush | $70 |\n\n[Review](https://example.com/review)\n\nSources: example.org'} />);
    expect(screen.getByRole('table')).toBeTruthy();
    expect(screen.getByRole('link', { name: /Review/ }).getAttribute('href')).toBe('https://example.com/review');
    expect(screen.getByRole('link', { name: /example.org/ }).getAttribute('href')).toBe('https://example.org/');
  });
  it('keeps code literal and rejects executable links and HTML', () => {
    render(<AgentResponse content={'```markdown\n## Literal heading\n```\n\n[Bad](javascript:alert%281%29)\n\n<script>alert(1)</script>'} />);
    expect(screen.getByText('## Literal heading').tagName).toBe('CODE');
    expect(screen.queryByRole('link')).toBeNull();
    expect(document.querySelector('script')).toBeNull();
  });
});

const reportedPie = { schemaVersion: '1.0', type: 'pie', title: "What's Working Today 🎯", labels: ['Tables', 'Charts', 'Comparisons', 'Emojis', 'Details blocks'], series: [{ name: 'Ready', values: [20, 20, 20, 20, 20] }] };
describe('structured replies and long lines', () => {
  it('renders the reported JSON as a pie chart inside the reply', () => {
    render(<AgentResponse content={'Data visualizations ✨\n\n```json\n' + JSON.stringify(reportedPie) + '\n```\n\nMore normal text.'} />);
    expect(screen.getByRole('img', { name: reportedPie.title })).toBeTruthy();
    expect(screen.getByText('More normal text.')).toBeTruthy();
    expect(document.querySelector('pre')).toBeNull();
    expect(document.body.textContent).not.toContain('schemaVersion');
  });
  it('also handles a raw JSON card paragraph and the canonical chart schema', () => {
    render(<AgentResponse content={JSON.stringify({ ...reportedPie, type: 'chart', chart: 'pie' })} />);
    expect(screen.getByRole('img', { name: reportedPie.title })).toBeTruthy();
  });
  it('leaves invalid chart data and explicitly typed programming examples as code', () => {
    const invalid = { ...reportedPie, series: [{ name: 'Bad', values: [-1, 20, 20, 20, 20] }] };
    render(<AgentResponse content={'```json\n' + JSON.stringify(invalid) + '\n```\n\n```javascript\n' + JSON.stringify(reportedPie) + '\n```'} />);
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.getAllByRole('region', { name: 'Code block' })).toHaveLength(2);
    expect(document.querySelectorAll('pre code')).toHaveLength(2);
  });
  it('keeps preserved code lines keyboard-scrollable and prose in paragraphs', () => {
    const line = 'const value = "' + 'x'.repeat(2000) + '";';
    render(<AgentResponse content={'A normal paragraph that wraps.\n\n```js\n' + line + '\n```'} />);
    expect(screen.getByText('A normal paragraph that wraps.').tagName).toBe('P');
    const code = screen.getByRole('region', { name: 'Code block' });
    expect(code.getAttribute('tabindex')).toBe('0');
    expect(code.textContent).toContain(line);
  });
});

describe('layouts chosen for a plain-text reply', () => {
  const steps = 'Here is how.\n\n1. Unplug the router\n2. Wait ten seconds\n3. Plug it back in\n\nThat usually fixes it.';
  it('turns the numbered list into a checklist without changing a word', () => {
    render(<AgentResponse content={steps} layout="steps" />);
    const boxes = screen.getAllByRole('checkbox');
    expect(boxes.length).toBe(3);
    expect(screen.getByText('Wait ten seconds')).toBeTruthy(); expect(screen.getByText('That usually fixes it.')).toBeTruthy();
    fireEvent.click(boxes[0]); expect((boxes[0] as HTMLInputElement).checked).toBe(true);
  });
  it('leaves bullet lists inside steps alone, and shows the reply as it is without a layout', () => {
    render(<AgentResponse content={'1. First\n   - a detail\n2. Second\n3. Third'} layout="steps" />);
    expect(screen.getAllByRole('checkbox').length).toBe(3);
    cleanup();
    render(<AgentResponse content={steps} />);
    expect(screen.queryByRole('checkbox')).toBeNull();
  });
  it('marks the answer and list layouts for styling only', () => {
    const { container } = render(<><AgentResponse content={'It costs $12.\n\nMore detail.'} layout="answer" /><AgentResponse content={'- A\n- B\n- C'} layout="list" /></>);
    expect(container.querySelector('.layout-answer > p')?.textContent).toBe('It costs $12.');
    expect(container.querySelectorAll('.layout-list > ul > li').length).toBe(3);
  });
});

describe('a reply whose card is already stored', () => {
  const withFence = 'Here are the options.\n\n```lumina\n' + JSON.stringify({ schemaVersion: '1.0', type: 'callout', tone: 'tip', text: 'Book early.' }) + '\n```';
  it('does not draw the card a second time from its own text', () => {
    render(<AgentResponse content={withFence} cardsStored />);
    expect(screen.queryByText('Book early.')).toBeNull(); expect(screen.getByText('Here are the options.')).toBeTruthy();
  });
  it('still draws it while no stored card exists yet', () => {
    render(<AgentResponse content={withFence} />);
    expect(screen.getAllByText('Book early.').length).toBe(1);
  });
});
