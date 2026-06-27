import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState, type JSX } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { Button, Checkbox, Form, RadioGroup, Select, TextField } from './index.js';

describe('UI kit', () => {
  it('TextField: label is associated and onValueChange fires', async () => {
    const user = userEvent.setup();
    function Wrap(): JSX.Element {
      const [v, setV] = useState('');
      return <TextField label="Name" value={v} onValueChange={setV} />;
    }
    render(<Wrap />);
    const input = screen.getByLabelText('Name');
    await user.type(input, 'hi');
    expect(input).toHaveValue('hi');
  });

  it('TextField: shows an error message and marks the input invalid', () => {
    render(
      <TextField label="Email" value="" onValueChange={vi.fn()} error="Required" />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Required');
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true');
  });

  it('Select: renders options and reports the chosen value', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Select
        label="Type"
        value="a"
        onValueChange={onChange}
        options={[
          { value: 'a', label: 'Alpha' },
          { value: 'b', label: 'Beta' },
        ]}
      />,
    );
    await user.selectOptions(screen.getByLabelText('Type'), 'b');
    expect(onChange).toHaveBeenCalledWith('b');
  });

  it('Checkbox: toggles and reports the checked state', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Checkbox label="Agree" checked={false} onCheckedChange={onChange} />);
    await user.click(screen.getByLabelText('Agree'));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('RadioGroup: selects an option', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <RadioGroup
        legend="Size"
        value="s"
        onValueChange={onChange}
        options={[
          { value: 's', label: 'Small' },
          { value: 'l', label: 'Large' },
        ]}
      />,
    );
    await user.click(screen.getByLabelText('Large'));
    expect(onChange).toHaveBeenCalledWith('l');
  });

  it('Button: primary variant calls onClick', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Go</Button>);
    await user.click(screen.getByRole('button', { name: 'Go' }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('Form: calls onSubmit with default prevented', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <Form onSubmit={onSubmit}>
        <Button type="submit">Save</Button>
      </Form>,
    );
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(onSubmit).toHaveBeenCalledOnce();
  });
});
