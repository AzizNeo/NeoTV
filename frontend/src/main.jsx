import '@/core/config/zodSetup'; // first: before any schema parses (CSP: no eval)
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@/shared/styles/global.css';
import { App } from '@/app/App';
import { BootError } from '@/app/BootError';
import { createRegistry } from '@/app/bootstrap';

const root = createRoot(document.getElementById('root'));

createRegistry()
  .then((registry) => root.render(<StrictMode><App registry={registry} /></StrictMode>))
  .catch((error) => {
    console.error(error);
    root.render(<BootError error={error} />);
  });
