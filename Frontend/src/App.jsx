import { BrowserRouter, Routes, Route } from 'react-router-dom'
import VoiceAgent from './pages/VoiceAgent.jsx'
import Supervisor from './pages/Supervisor.jsx'
import Analytics from './pages/Analytics.jsx'

export default function App() {
    return (
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
            <Routes>
                <Route path="/" element={<VoiceAgent />} />
                <Route path="/supervisor" element={<Supervisor />} />
                <Route path="/analytics" element={<Analytics />} />
            </Routes>
        </BrowserRouter>
    )
}
