import '@fontsource-variable/inter';
import './styles/app.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { canonical } from './lib/path';
import { DataProvider } from './state/data';
import { SettingsProvider } from './state/settings';

const fix = canonical(location.pathname, location.search, location.hash);
if (fix) history.replaceState(null, '', fix);

createRoot(document.getElementById('root')!).render(
  <StrictMode><SettingsProvider><DataProvider><App /></DataProvider></SettingsProvider></StrictMode>);
