import { useEffect, useState } from 'react'
import { Link, Route, Routes } from 'react-router-dom'
import CheckColumns from './CheckColumns'
import Cleaning from './Cleaning'
import Upload from './Upload'

const placeholders: [string, string][] = [
  ['/sign-in', 'Sign in'],
  ['/sign-up', 'Sign up'],
  ['/projects', 'Projects'],
  ['/upload', 'Upload'],
  ['/check-columns', 'Check columns'],
  ['/cleaning', 'Cleaning review'],
  ['/report', 'Report'],
]

function Home() {
  const [status, setStatus] = useState('checking...')
  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then((j) => setStatus(`API ${j.status}, database ${j.db ? 'connected' : 'unavailable'}`))
      .catch(() => setStatus('API unreachable'))
  }, [])
  return (
    <>
      <h1>Verbatim</h1>
      <p className="muted">Turn a spreadsheet into a short report.</p>
      <p>{status}</p>
    </>
  )
}

const Placeholder = ({ title }: { title: string }) => (
  <>
    <h1>{title}</h1>
    <p className="muted">Coming soon.</p>
  </>
)

export default function App() {
  return (
    <div className="page">
      <nav className="top">
        <Link to="/">Home</Link>
        {placeholders.map(([path, title]) => (
          <Link key={path} to={path}>{title}</Link>
        ))}
      </nav>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/upload" element={<Upload />} />
        <Route path="/check-columns" element={<CheckColumns />} />
        <Route path="/cleaning" element={<Cleaning />} />
        {placeholders
          .filter(([p]) => p !== '/upload' && p !== '/check-columns' && p !== '/cleaning')
          .map(([path, title]) => (
          <Route key={path} path={path} element={<Placeholder title={title} />} />
        ))}
        <Route path="*" element={<Placeholder title="Not found" />} />
      </Routes>
    </div>
  )
}
