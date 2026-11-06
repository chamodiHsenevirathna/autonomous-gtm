import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createApi } from './api';
import App from './App';
import ErrorBoundary from './components/ErrorBoundary';
import { AppProvider } from './context';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppProvider api={createApi()}>
      <ErrorBoundary><App /></ErrorBoundary>
    </AppProvider>
  </StrictMode>,
);
