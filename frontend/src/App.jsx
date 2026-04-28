import React from 'react'
import ChatInterface from './components/ChatInterface'
import { useChat } from './hooks/useChat'

export default function App() {
  const {
    messages,
    isLoading,
    sessionId,
    scene,
    useStreaming,
    setUseStreaming,
    sendMessage,
    clearSession,
  } = useChat()

  return (
    <div className="app">
      <ChatInterface
        messages={messages}
        isLoading={isLoading}
        sessionId={sessionId}
        scene={scene}
        useStreaming={useStreaming}
        setUseStreaming={setUseStreaming}
        onSend={sendMessage}
        onClear={clearSession}
      />
    </div>
  )
}
