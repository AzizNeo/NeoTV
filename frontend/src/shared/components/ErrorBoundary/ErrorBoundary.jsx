import { Component } from 'react';
import PropTypes from 'prop-types';
import styles from './ErrorBoundary.module.css';

/**
 * Catches render errors. `resetKey` (e.g. the route path) clears the error
 * when the user navigates away, so one broken page never bricks the shell.
 * Named contract errors (FeatureContractError …) show their message: they are
 * configuration problems meant to be read by the developer.
 * Texts come from the caller (`labels`): shared components never depend on the i18n core.
 */
const DEFAULT_LABELS = { title: 'Bir şeyler ters gitti.', unknown: 'Beklenmeyen bir arayüz hatası oluştu.', reload: 'Sayfayı yenile' };

export class ErrorBoundary extends Component {
  state = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error) {
    return { error };
  }

  static getDerivedStateFromProps(props, state) {
    if (props.resetKey !== state.resetKey) return { error: null, resetKey: props.resetKey };
    return null;
  }

  componentDidCatch(error, info) {
    console.error('ErrorBoundary', error, info?.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    if (this.props.fallback) return this.props.fallback;
    const labels = { ...DEFAULT_LABELS, ...this.props.labels };
    return (
      <div className={styles.container} role="alert">
        <div className={styles.content}>
          <h2>{labels.title}</h2>
          <p className={styles.message}>
            {error.name?.endsWith('Error') && error.name !== 'Error' ? `${error.name}: ` : ''}
            {error.message || labels.unknown}
          </p>
          <button className={styles.button} onClick={() => window.location.reload()}>
            {labels.reload}
          </button>
        </div>
      </div>
    );
  }
}

ErrorBoundary.propTypes = {
  children: PropTypes.node.isRequired,
  fallback: PropTypes.node,
  resetKey: PropTypes.any,
  labels: PropTypes.shape({ title: PropTypes.string, unknown: PropTypes.string, reload: PropTypes.string }),
};
