import React from 'react';
import ReactDOM from 'react-dom/client';
import { VerificationFlow } from './components/VerificationFlow';
import './styles/verification.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <VerificationFlow 
      sessionId="demo-session"
      riskLevel="medium"
      language="en"
      onComplete={(result) => console.log('Complete:', result)}
      onError={(error) => console.error('Error:', error)}
    />
  </React.StrictMode>
);