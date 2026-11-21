import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from './context/AuthContext';
import AppLayout from './layouts/AppLayout';
import Login from './pages/auth/Login';
import ForgotPassword from './pages/auth/ForgotPassword';
import ResetPassword from './pages/auth/ResetPassword';
import AdminDashboard from './pages/admin/AdminDashboard';
import People from './pages/admin/People';
import Teams from './pages/admin/Teams';
import AuditLog from './pages/admin/AuditLog';
import Monitoring from './pages/admin/Monitoring';
import MyTeam from './pages/developer/MyTeam';
import EmployeeDashboard from './pages/employee/EmployeeDashboard';
import Tasks from './pages/tasks/Tasks';
import Reviews from './pages/reviews/Reviews';
import ReviewDetail from './pages/reviews/ReviewDetail';
import Profile from './pages/profile/Profile';
import WorkspaceIndex from './pages/workspace/WorkspaceIndex';
import Languages from './pages/admin/Languages';
import AISettings from './pages/admin/AISettings';
import Meetings from './pages/meetings/Meetings';
import Chat from './pages/chat/Chat';
import Recordings from './pages/recordings/Recordings';
import Reports from './pages/reports/Reports';
import { HOME } from './utils/format';

const Workspace = lazy(() => import('./pages/workspace/Workspace')); // Monaco is large: load on demand

/** Route guard. The backend repeats every check; this only keeps the UI honest. */
export function Guard({ roles, children }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(user.role)) return <Navigate to={HOME[user.role]} replace />;
  return children;
}

const page = (roles, element) => <Guard roles={roles}><div className="main">{element}</div></Guard>;

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <div className="empty">Loading…</div>;
  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to={HOME[user.role]} replace /> : <Login />} />
      <Route path="/forgot-password" element={user ? <Navigate to={HOME[user.role]} replace /> : <ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route element={<Guard><AppLayout /></Guard>}>
        <Route path="/admin" element={page(['admin'], <AdminDashboard />)} />
        <Route path="/people" element={page(['admin'], <People />)} />
        <Route path="/people/:userId" element={page(['admin', 'developer', 'onroll'], <Profile />)} />
        <Route path="/teams" element={page(['admin'], <Teams />)} />
        <Route path="/monitoring" element={page(['admin'], <Monitoring />)} />
        <Route path="/audit" element={page(['admin'], <AuditLog />)} />
        <Route path="/team" element={page(['developer', 'onroll'], <MyTeam />)} />
        <Route path="/onroll" element={page(['onroll', 'developer'], <EmployeeDashboard />)} />
        <Route path="/offroll" element={page(['offroll'], <EmployeeDashboard />)} />
        <Route path="/intern" element={page(['intern'], <EmployeeDashboard />)} />
        <Route path="/tasks" element={page(null, <Tasks />)} />
        <Route path="/tasks/:taskId" element={page(null, <Tasks />)} />
        <Route path="/reviews" element={page(null, <Reviews />)} />
        <Route path="/reviews/:subId" element={page(null, <ReviewDetail />)} />
        <Route path="/profile" element={page(null, <Profile />)} />
        <Route path="/languages" element={page(['admin'], <Languages />)} />
        <Route path="/ai-settings" element={page(['admin'], <AISettings />)} />
        <Route path="/meetings" element={page(null, <Meetings />)} />
        <Route path="/chat" element={page(null, <Chat />)} />
        <Route path="/recordings" element={page(null, <Recordings />)} />
        <Route path="/reports" element={page(null, <Reports />)} />
        <Route path="/workspace" element={page(['developer', 'onroll', 'offroll', 'intern'], <WorkspaceIndex />)} />
        <Route path="/workspace/:taskId" element={
          <Guard><Suspense fallback={<div className="empty">Loading editor…</div>}><Workspace /></Suspense></Guard>} />
      </Route>
      <Route path="*" element={<Navigate to={user ? HOME[user.role] : '/login'} replace />} />
    </Routes>
  );
}
