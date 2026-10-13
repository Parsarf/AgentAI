import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
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
