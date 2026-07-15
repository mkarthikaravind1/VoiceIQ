import { BrowserRouter, Routes, Route } from 'react-router-dom'
import VoiceAgent from './pages/VoiceAgent.jsx'

export default function App() {
    return (
        <BrowserRouter>
            <Routes>
                <Route path="/" element={<VoiceAgent />} />
            </Routes>
        </BrowserRouter>
    )
}