import { describe, expect, it, beforeEach } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { ThemeProvider, useTheme } from './ThemeProvider';

function Probe() {
  const { theme, resolved, setTheme } = useTheme();
  return (
    <>
      <output>{`${theme}/${resolved}`}</output>
      <button type="button" onClick={() => setTheme('light')}>light</button>
      <button type="button" onClick={() => setTheme('system')}>system</button>
    </>
  );
}

describe('ThemeProvider', () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it('follows the system by default (dark here) and pins + remembers a choice', () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByRole('status')).toHaveTextContent('system/dark');
    expect(document.documentElement.dataset.theme).toBe('dark');

    act(() => screen.getByText('light').click());
    expect(screen.getByRole('status')).toHaveTextContent('light/light');
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(localStorage.getItem('neotv.theme')).toBe('light');
  });

  it('restores a saved choice and ignores garbage in storage', () => {
    localStorage.setItem('neotv.theme', 'light');
    const { unmount } = render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByRole('status')).toHaveTextContent('light/light');
    unmount();
    localStorage.setItem('neotv.theme', 'neon');
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByRole('status')).toHaveTextContent('system/dark');
  });
});
