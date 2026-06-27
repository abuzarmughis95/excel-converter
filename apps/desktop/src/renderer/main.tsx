import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App.js';
import { applyStoredThemeEarly } from './theme/ThemeContext.js';
import './styles.css';

// Apply the stored theme before React mounts to avoid a flash of the wrong
// colour scheme. ThemeProvider takes over once mounted.
applyStoredThemeEarly();

const container = document.getElementById('root');
if (container === null) {
  throw new Error('Root element #root not found');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
