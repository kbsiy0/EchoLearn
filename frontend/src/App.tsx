import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import { HomePage } from './routes/HomePage';
import { PlayerPage } from './routes/PlayerPage';

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-900 text-white flex flex-col">
        {/* Header */}
        <header className="bg-gray-800 border-b border-gray-700 px-6 py-3 shrink-0">
          <Link to="/" className="text-xl font-bold tracking-wide hover:text-blue-400 transition-colors">
            EchoLearn
          </Link>
        </header>

        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/watch/:videoId" element={<PlayerPage />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}

export default App;
