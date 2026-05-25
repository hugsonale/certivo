/**
 * Fallback Options Component
 * Alternative verification methods when camera unavailable
 */

import React from 'react';

export const FallbackOptions = ({ reason, language, onSelectMethod }) => {
  const fallbackMethods = [
    {
      id: 'document_upload',
      icon: '📄',
      title: {
        en: 'Upload ID Document',
        es: 'Subir Documento de Identidad'
      },
      description: {
        en: 'Upload a photo of your government-issued ID',
        es: 'Sube una foto de tu identificación oficial'
      },
      estimatedTime: '2-3 minutes'
    },
    {
      id: 'sms_verification',
      icon: '📱',
      title: {
        en: 'SMS Verification',
        es: 'Verificación por SMS'
      },
      description: {
        en: 'Receive a verification code via text message',
        es: 'Recibe un código de verificación por mensaje de texto'
      },
      estimatedTime: '1 minute'
    },
    {
      id: 'email_verification',
      icon: '📧',
      title: {
        en: 'Email Verification',
        es: 'Verificación por Correo'
      },
      description: {
        en: 'Receive a verification link via email',
        es: 'Recibe un enlace de verificación por correo'
      },
      estimatedTime: '1-2 minutes'
    },
    {
      id: 'support_assisted',
      icon: '💬',
      title: {
        en: 'Assisted Verification',
        es: 'Verificación Asistida'
      },
      description: {
        en: 'Get help from our support team',
        es: 'Obtén ayuda de nuestro equipo de soporte'
      },
      estimatedTime: '5-10 minutes'
    }
  ];
  
  const reasonMessages = {
    camera_not_found: {
      en: {
        title: 'Camera Not Detected',
        message: 'We couldn\'t detect a camera on your device. Please choose an alternative verification method:'
      },
      es: {
        title: 'Cámara No Detectada',
        message: 'No pudimos detectar una cámara en tu dispositivo. Por favor elige un método alternativo:'
      }
    },
    camera_permission_denied: {
      en: {
        title: 'Camera Access Needed',
        message: 'Camera access is required for video verification. You can allow camera access or choose an alternative method:'
      },
      es: {
        title: 'Se Necesita Acceso a la Cámara',
        message: 'Se requiere acceso a la cámara para verificación. Puedes permitir el acceso o elegir un método alternativo:'
      }
    }
  };
  
  const currentReason = reasonMessages[reason]?.[language] || reasonMessages.camera_not_found.en;
  
  return (
    <div className="fallback-options" role="region" aria-label="Alternative verification methods">
      <div className="fallback-header">
        <h2>{currentReason.title}</h2>
        <p>{currentReason.message}</p>
      </div>
      
      <div className="fallback-methods">
        {fallbackMethods.map((method) => (
          <button
            key={method.id}
            onClick={() => onSelectMethod(method.id)}
            className="fallback-method-card"
            aria-label={`${method.title[language]}: ${method.description[language]}. Estimated time: ${method.estimatedTime}`}
          >
            <div className="method-icon" aria-hidden="true">{method.icon}</div>
            <div className="method-content">
              <h3>{method.title[language]}</h3>
              <p>{method.description[language]}</p>
              <span className="method-time">
                ⏱️ {method.estimatedTime}
              </span>
            </div>
            <div className="method-arrow" aria-hidden="true">→</div>
          </button>
        ))}
      </div>
      
      <div className="fallback-footer">
        <p className="help-text">
          {language === 'en' 
            ? 'Need help? Contact our support team at support@certivo.com'
            : 'Contacta a nuestro equipo en support@certivo.com'
          }
        </p>
      </div>
    </div>
  );
};