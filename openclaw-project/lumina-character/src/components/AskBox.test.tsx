import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import AskBox from './AskBox';
import { questionTitle, rememberText, type Question } from '../lib/live';

const q: Question = { id: 'q1', title: 'Which size?', field: 'size', menu: true, options: [{ id: 'o1', label: 'Small' }, { id: 'o2', label: 'Medium' }] };
const setup = (question = q, menuOpen = false) => {
  const onAnswer = vi.fn(); const onMenu = vi.fn();
  render(<AskBox question={question} menuOpen={menuOpen} busy={false} onMenu={onMenu} onAnswer={onAnswer} />);
  return { onAnswer, onMenu };
};

describe('the question box', () => {
  it('sends the picked option only after a pick, and never saves it unless ticked', () => {
    const { onAnswer } = setup();
    const use = screen.getByText('Use this') as HTMLButtonElement;
    expect(use.disabled).toBe(true);
    fireEvent.click(screen.getByText('Medium')); fireEvent.click(use);
    expect(onAnswer).toHaveBeenCalledWith({ option: 'o2', remember: false });
  });

  it('offers to remember the choice by name and sends the tick', () => {
    const { onAnswer } = setup();
    expect(screen.queryByLabelText(/Remember/)).toBeNull();                         // nothing to remember before a pick
    fireEvent.click(screen.getByText('Small'));
    fireEvent.click(screen.getByLabelText('Remember size: Small for next time')); fireEvent.click(screen.getByText('Use this'));
    expect(onAnswer).toHaveBeenCalledWith({ option: 'o1', remember: true });
  });

  it('opens the page to choose there, and Continue resumes the run', () => {
    const { onMenu } = setup();
    fireEvent.click(screen.getByText('View full menu')); expect(onMenu).toHaveBeenCalled();
  });

  it('with the page open it says what to do and offers Continue', () => {
    const { onAnswer } = setup(q, true);
    expect(screen.getByText(/Choose on the page below/)).toBeTruthy(); expect(screen.queryByText('Use this')).toBeNull();
    fireEvent.click(screen.getByText('Continue')); expect(onAnswer).toHaveBeenCalledWith({ resume: true });
  });

  it('a question with no list sends the customer straight to the page', () => {
    const none: Question = { id: 'q2', title: '', field: '', menu: true, options: [] };
    setup(none);
    expect(questionTitle(none)).toMatch(/choose on the page/); expect(screen.getByText('Choose on the page')).toBeTruthy(); expect(screen.queryByText('Use this')).toBeNull();
    expect(rememberText(none, null)).toBe('');
  });
});
