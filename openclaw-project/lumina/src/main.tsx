import '@fontsource-variable/inter';
import './styles/app.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { DataProvider } from './state/data';
import { SettingsProvider } from './state/settings';

createRoot(document.getElementById('root')!).render(
  <StrictMode><SettingsProvider><DataProvider><App /></DataProvider></SettingsProvider></StrictMode>);
