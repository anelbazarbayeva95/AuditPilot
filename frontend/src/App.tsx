import { Navigate, Route, Routes } from "react-router-dom"

import { AuditProgressPage } from "@/pages/AuditProgressPage"
import { AuditResultsPage } from "@/pages/AuditResultsPage"
import { UrlInputPage } from "@/pages/UrlInputPage"

function App() {
  return (
    <div className="min-h-svh bg-background">
      <Routes>
        <Route path="/" element={<UrlInputPage />} />
        <Route path="/progress" element={<AuditProgressPage />} />
        <Route path="/results" element={<AuditResultsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  )
}

export default App
