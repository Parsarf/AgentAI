import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import Shell from './components/Shell';
import Home from './pages/Home';
import Chat from './pages/Chat';
import Tasks from './pages/Tasks';
import Login from './pages/Login';
import { Automations, Browser, Calendar, Files, Integrations, Settings } from './pages/Info';
import { useData } from './state/data';

export default function App() {
  const { status } = useData();
  if (status === 'loading') return <div className="login"><p className="muted" role="status">Loading…</p></div>;
  if (status === 'error') return <div className="login"><p className="err" role="alert">Lumina could not reach the server. Check your connection and reload.</p></div>;
  if (status === 'anon') return <Login />;
  return (
    <BrowserRouter basename="/app">
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Home />} /><Route path="chat" element={<Chat />} /><Route path="chat/:id" element={<Chat />} />
          <Route path="tasks" element={<Tasks />} /><Route path="tasks/:id" element={<Tasks />} />
          <Route path="browser" element={<Browser />} /><Route path="files" element={<Files />} /><Route path="calendar" element={<Calendar />} />
          <Route path="automations" element={<Automations />} /><Route path="integrations" element={<Integrations />} /><Route path="settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>);
}
