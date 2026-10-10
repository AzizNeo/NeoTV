import PropTypes from 'prop-types';
import styles from './Button.module.css';

export const Button = ({
    children,
    onClick,
    variant = 'primary',
    size = 'md',
    disabled = false,
    fullWidth = false,
    type = 'button',
    className = '',
    ...props
}) => {
    const baseClass = styles.button;
    const variantClass = styles[`variant-${variant}`];
    const sizeClass = styles[`size-${size}`];
    const widthClass = fullWidth ? styles.fullWidth : '';

    const combinedClasses = [baseClass, variantClass, sizeClass, widthClass, className]
        .filter(Boolean)
        .join(' ');

    return (
        <button
            type={type}
            className={combinedClasses}
            onClick={disabled ? undefined : onClick}
            disabled={disabled}
            {...props}
        >
            {children}
        </button>
    );
};

Button.propTypes = {
    children: PropTypes.node.isRequired,
    onClick: PropTypes.func,
    variant: PropTypes.oneOf(['primary', 'secondary', 'danger', 'ghost']),
    size: PropTypes.oneOf(['sm', 'md', 'lg']),
    disabled: PropTypes.bool,
    fullWidth: PropTypes.bool,
    type: PropTypes.oneOf(['button', 'submit', 'reset']),
    className: PropTypes.string,
};
