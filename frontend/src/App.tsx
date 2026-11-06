import { HashRouter, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import Overview from './pages/Overview';
import Leads from './pages/Leads';
import { AccountList, AccountPage } from './pages/Accounts';
import Approvals from './pages/Approvals';
import { RunList, RunPage } from './pages/Runs';
import Alerts from './pages/Alerts';
import Audit from './pages/Audit';
import Evaluation from './pages/Evaluation';
import Feedback from './pages/Feedback';
import Demo from './pages/Demo';
import { Empty } from './components/ui';

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="leads" element={<Leads />} />
          <Route path="accounts" element={<AccountList />} />
          <Route path="accounts/:id" element={<AccountPage />} />
          <Route path="approvals" element={<Approvals />} />
          <Route path="approvals/:id" element={<Approvals />} />
          <Route path="runs" element={<RunList />} />
          <Route path="runs/:id" element={<RunPage />} />
          <Route path="alerts" element={<Alerts />} />
          <Route path="audit" element={<Audit />} />
          <Route path="evaluation" element={<Evaluation />} />
          <Route path="feedback" element={<Feedback />} />
          <Route path="demo" element={<Demo />} />
          <Route path="*" element={<Empty title="Page not found">Use the navigation to pick a page.</Empty>} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
