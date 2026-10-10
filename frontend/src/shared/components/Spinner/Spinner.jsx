import styles from './Spinner.module.css';
import PropTypes from 'prop-types';

export const Spinner = ({ size = 'md', color = 'primary', fullScreen = false }) => {
    const spinnerClass = `${styles.spinner} ${styles[`size-${size}`]} ${styles[`color-${color}`]}`;

    if (fullScreen) {
        return (
            <div className={styles.fullScreenOverlay} data-testid="spinner-overlay">
                <div className={spinnerClass} data-testid="spinner" />
            </div>
        );
    }

    return <div className={spinnerClass} data-testid="spinner" />;
};

Spinner.propTypes = {
    size: PropTypes.oneOf(['sm', 'md', 'lg']),
    color: PropTypes.oneOf(['primary', 'white']),
    fullScreen: PropTypes.bool,
};
