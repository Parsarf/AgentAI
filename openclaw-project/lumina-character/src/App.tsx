import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom';
import Shell from './components/Shell';
import Home from './pages/Home';
import Chat from './pages/Chat';
import History from './pages/History';
import Tasks from './pages/Tasks';
import Login from './pages/Login';
import Live from './pages/Live';
import { Automations, Calendar, Integrations, Settings } from './pages/Info';
import Files from './pages/Files';
import { useData } from './state/data';

/** Old /browser/<task> links (saved or sent earlier) land on the same task in Live view. */
function OldBrowserLink() { const { id } = useParams(); return <Navigate to={`/live/${id ?? ''}`} replace />; }

export default function App() {
  const { status } = useData();
  if (status === 'loading') return <div className="login"><p className="muted" role="status">Loading…</p></div>;
  if (status === 'error') return <div className="login"><p className="err" role="alert">Lumina could not reach the server. Check your connection and reload.</p></div>;
  if (status === 'anon') return <Login />;
  return (
    <BrowserRouter basename="/app">
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Chat />} /><Route path="home" element={<Home />} /><Route path="history" element={<History />} /><Route path="chat" element={<Chat />} /><Route path="chat/:id" element={<Chat />} />
          <Route path="tasks" element={<Tasks />} /><Route path="tasks/:id" element={<Tasks />} />
          <Route path="live" element={<Live />} /><Route path="live/:id" element={<Live />} /><Route path="browser" element={<Navigate to="/live" replace />} /><Route path="browser/:id" element={<OldBrowserLink />} /><Route path="files" element={<Files />} /><Route path="calendar" element={<Calendar />} />
          <Route path="automations" element={<Automations />} /><Route path="integrations" element={<Integrations />} /><Route path="settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>);
}
