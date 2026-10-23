import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import FieldsBox from './FieldsBox';
import { fieldLabel, type Question } from '../lib/live';

const q = (extra: Partial<Question> = {}): Question => ({ id: 'q1', title: 'Your delivery details', field: '', menu: true, kind: 'fields', options: [], fields: [
  { id: 'f1', label: 'Full name *', key: 'full name', sensitive: false, input_type: 'text', prefill: '' },
  { id: 'f2', label: 'Email address', key: 'email address', sensitive: false, input_type: 'email', prefill: 'ada@example.test' },
  { id: 'f3', label: 'Order notes', key: 'order notes', sensitive: true, input_type: 'text', prefill: '' },
  { id: 'f4', label: 'Street address', key: 'street address', sensitive: false, input_type: 'text', prefill: '' }], ...extra });
const setup = (question = q(), menuOpen = false) => {
  const onAnswer = vi.fn(); const onMenu = vi.fn(); const onCancel = vi.fn();
  const view = render(<FieldsBox question={question} menuOpen={menuOpen} busy={false} onMenu={onMenu} onAnswer={onAnswer} onCancel={onCancel} />);
  return { onAnswer, onMenu, onCancel, ...view };
};
const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe('the details box', () => {
  it('asks one field at a time, never a sensitive one, and keeps what was typed when going back', () => {
    setup();
    expect(screen.getByText('1 of 3')).toBeTruthy(); expect(screen.getByLabelText('Full name')).toBeTruthy();
    const next = screen.getByText('Next') as HTMLButtonElement; expect(next.disabled).toBe(true);           // nothing typed yet
    type('Full name', 'Ada Lovelace'); fireEvent.click(screen.getByText('Next'));
    expect(screen.getByText('2 of 3')).toBeTruthy(); expect(screen.queryByLabelText('Order notes')).toBeNull();
    fireEvent.click(screen.getByText('Back')); expect((screen.getByLabelText('Full name') as HTMLInputElement).value).toBe('Ada Lovelace');
  });

  it('uses saved info as a starting value, says so, and lets it be changed', () => {
    setup(); type('Full name', 'Ada'); fireEvent.click(screen.getByText('Next'));
    expect((screen.getByLabelText('Email address') as HTMLInputElement).value).toBe('ada@example.test'); expect(screen.getByText(/From your saved info/)).toBeTruthy();
    type('Email address', 'new@example.test'); expect(screen.queryByText(/From your saved info/)).toBeNull();
  });

  it('Save & next remembers only that field, and the review step sends exactly what was entered', () => {
    const { onAnswer } = setup();
    type('Full name', 'Ada Lovelace'); fireEvent.click(screen.getByText('Save & next'));              // saved for later forms
    fireEvent.click(screen.getByText('Next'));                                                          // the email, as it is: not saved
    type('Street address', '1 Main St'); fireEvent.click(screen.getByText('Next'));
    expect(screen.getByText('Review')).toBeTruthy(); expect(screen.getByText('1 Main St')).toBeTruthy(); expect(screen.getByText('will be saved')).toBeTruthy();
    expect(screen.getByText(/You will type these yourself on the page: Order notes/)).toBeTruthy();
    fireEvent.click(screen.getByText('Fill it in'));
    expect(onAnswer).toHaveBeenCalledWith({ fields: { f1: 'Ada Lovelace', f2: 'ada@example.test', f4: '1 Main St' }, remember_fields: ['f1'] });
  });

  it('can skip a field, edit from the review, and never sends an empty field', () => {
    const { onAnswer } = setup();
    type('Full name', 'Ada'); fireEvent.click(screen.getByText('Next'));
    fireEvent.click(screen.getByText('Skip this one')); fireEvent.click(screen.getByText('Skip this one'));
    expect(screen.getByText('Review')).toBeTruthy();
    fireEvent.click(screen.getAllByText('Edit')[0]); expect(screen.getByText('1 of 3')).toBeTruthy();
    fireEvent.click(screen.getByText('Next')); fireEvent.click(screen.getByText('Skip this one')); fireEvent.click(screen.getByText('Skip this one'));
    fireEvent.click(screen.getByText('Fill it in')); expect(onAnswer).toHaveBeenCalledWith({ fields: { f1: 'Ada', f2: 'ada@example.test' }, remember_fields: [] });
  });

  it('lets the person cancel at any step and enter the details themselves on the page', () => {
    const { onCancel, onMenu, onAnswer, rerender } = setup();
    fireEvent.click(screen.getByText('Cancel')); expect(onCancel).toHaveBeenCalled();
    fireEvent.click(screen.getByText(/enter these myself on the page/)); expect(onMenu).toHaveBeenCalled();
    rerender(<FieldsBox question={q()} menuOpen busy={false} onMenu={onMenu} onAnswer={onAnswer} onCancel={onCancel} />);
    expect(screen.getByText(/Click the fields in the browser below/)).toBeTruthy();
    fireEvent.click(screen.getByText('Continue')); expect(onAnswer).toHaveBeenCalledWith({ resume: true });
  });

  it('cleans a field label the way a person would say it', () => {
    expect(fieldLabel('Full name *')).toBe('Full name'); expect(fieldLabel('  Phone   number: ')).toBe('Phone number'); expect(fieldLabel('*')).toBe('Details');
  });
});
