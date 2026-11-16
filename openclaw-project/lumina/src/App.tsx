import { lazy, Suspense, type ReactElement } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom';
import Shell from './components/Shell';
import Home from './pages/Home';
import Chat from './pages/Chat';
import History from './pages/History';
import Activity from './pages/Activity';
import Login from './pages/Login';
import Live from './pages/Live';
import Inbox from './pages/Inbox';
import CalendarPage from './pages/CalendarPage';
import { Integrations, Settings } from './pages/Info';
import Files from './pages/Files';
import { useData } from './state/data';
import Workspace from './components/frame/Workspace';

/** A page not yet moved into the frame: shown in the canvas in its old form, so the app is whole at every phase. */
const old = (title: string, page: ReactElement) => <Workspace title={title} backdrop={title === 'Home'}>{page}</Workspace>;

/** Old /browser/<task> links (saved or sent earlier) land on the same task in Live view. */
/** Old /tasks/<id> links (saved or sent earlier) open the same item in Activity. */
function OldTaskLink() { const { id } = useParams(); return <Navigate to={`/activity/${id ?? ''}`} replace />; }
function OldBrowserLink() { const { id } = useParams(); return <Navigate to={`/live/${id ?? ''}`} replace />; }

const Gallery = lazy(() => import('./gen/Gallery'));
const FrameStress = lazy(() => import('./gen/FrameStress'));
export default function App() {
  const { status } = useData();
  if (status === 'loading') return <div className="login"><p className="muted" role="status">Loading…</p></div>;
  if (status === 'error') return <div className="login"><p className="err" role="alert">Lumina could not reach the server. Check your connection and reload.</p></div>;
  if (status === 'anon') return <Login />;
  return (
    <BrowserRouter basename="/app">
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Chat />} /><Route path="home" element={<Home />} /><Route path="history" element={old('Chat history', <History />)} /><Route path="chat" element={<Chat />} /><Route path="chat/:id" element={<Chat />} />
          <Route path="gen-gallery" element={<Suspense fallback={null}><Gallery /></Suspense>} /><Route path="frame-stress/:kind" element={<Suspense fallback={null}><FrameStress /></Suspense>} /><Route path="activity" element={<Activity />} /><Route path="activity/:id" element={<Activity />} /><Route path="tasks" element={<Navigate to="/activity" replace />} /><Route path="tasks/:id" element={<OldTaskLink />} />
          <Route path="live" element={old('Activity', <Live />)} /><Route path="live/:id" element={old('Activity', <Live />)} /><Route path="browser" element={<Navigate to="/live" replace />} /><Route path="browser/:id" element={<OldBrowserLink />} /><Route path="files" element={<Files />} /><Route path="inbox" element={<Inbox />} /><Route path="calendar" element={<CalendarPage />} />
          <Route path="automations" element={<Navigate to="/activity" replace />} /><Route path="integrations" element={old('Integrations', <Integrations />)} /><Route path="settings" element={old('Settings', <Settings />)} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>);
}
