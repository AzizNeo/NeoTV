import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { Modal } from './Modal';

describe('Modal Component', () => {
    it('does not render when isOpen is false', () => {
        render(<Modal isOpen={false} onClose={vi.fn()} title="Test">Content</Modal>);
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('renders correctly when isOpen is true', () => {
        render(<Modal isOpen={true} onClose={vi.fn()} title="Test Title">Test Content</Modal>);
        expect(screen.getByRole('dialog')).toBeInTheDocument();
        expect(screen.getByText('Test Title')).toBeInTheDocument();
        expect(screen.getByText('Test Content')).toBeInTheDocument();
    });

    it('calls onClose when close button is clicked', () => {
        const handleClose = vi.fn();
        render(<Modal isOpen={true} onClose={handleClose} title="Test">Content</Modal>);
        fireEvent.click(screen.getByLabelText('Kapat'));
        expect(handleClose).toHaveBeenCalledTimes(1);
    });
});
