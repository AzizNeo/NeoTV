import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { Spinner } from './Spinner';

describe('Spinner Component', () => {
    it('renders correctly', () => {
        render(<Spinner />);
        expect(screen.getByTestId('spinner')).toBeInTheDocument();
    });

    it('renders fullscreen overlay when wrapper is true', () => {
        render(<Spinner fullScreen={true} />);
        expect(screen.getByTestId('spinner-overlay')).toBeInTheDocument();
    });
});
