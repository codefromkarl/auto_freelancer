'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getMessageThreads,
  getMessages,
  sendMessage,
  markThreadAsRead,
  getUnreadCount,
} from '@/lib/api';
import {
  MessageSquare,
  Send,
  User,
  Clock,
  CheckCheck,
  Sparkles,
  ChevronRight,
  Archive,
  Trash2,
  Search,
  Bell,
  Mail,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Message, MessageThread } from '@/lib/types';

export default function MessagesPage() {
  const [selectedThread, setSelectedThread] = useState<MessageThread | null>(null);
  const [newMessage, setNewMessage] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [filter, setFilter] = useState<'all' | 'unread'>('all');

  const queryClient = useQueryClient();

  const {
    data: threads = [],
    isLoading,
    error: threadsError,
  } = useQuery({
    queryKey: ['messageThreads'],
    queryFn: getMessageThreads,
  });

  const { data: unreadCount = 0 } = useQuery({
    queryKey: ['unreadCount'],
    queryFn: getUnreadCount,
  });

  const sendMessageMutation = useMutation({
    mutationFn: ({
      threadId,
      content,
      messageType,
    }: {
      threadId: number;
      content: string;
      messageType: string;
    }) => sendMessage(threadId, content, messageType),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['messageThreads'] });
      queryClient.invalidateQueries({ queryKey: ['messages'] });
      setNewMessage('');
    },
  });

  const markThreadReadMutation = useMutation({
    mutationFn: (threadId: number) => markThreadAsRead(threadId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['messageThreads'] });
      queryClient.invalidateQueries({ queryKey: ['unreadCount'] });
    },
  });

  const { data: selectedMessages = [], error: messagesError } = useQuery({
    queryKey: ['messages', selectedThread?.thread_id],
    queryFn: () => getMessages(selectedThread!.thread_id),
    enabled: !!selectedThread,
  });

  const filteredThreads = threads.filter((thread) => {
    const matchesSearch = thread.project_title.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesFilter = filter === 'unread' ? thread.unread_count > 0 : true;
    return matchesSearch && matchesFilter;
  });

  const formatTime = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffHours = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60));

    if (diffHours < 1) {
      return '刚刚';
    } else if (diffHours < 24) {
      return `${diffHours}小时前`;
    } else if (diffHours < 48) {
      return '昨天';
    } else {
      return date.toLocaleDateString();
    }
  };

  const getMessageTypeBadge = (type: string) => {
    switch (type) {
      case 'interview':
        return (
          <Badge variant="outline" className="text-blue-500 border-blue-500">
            面试
          </Badge>
        );
      case 'offer':
        return (
          <Badge variant="outline" className="text-green-500 border-green-500">
            录用
          </Badge>
        );
      case 'inquiry':
        return (
          <Badge variant="outline" className="text-orange-500 border-orange-500">
            咨询
          </Badge>
        );
      default:
        return null;
    }
  };

  const handleSelectThread = (thread: MessageThread) => {
    setSelectedThread(thread);
    if (thread.unread_count > 0) {
      markThreadReadMutation.mutate(thread.thread_id);
    }
  };

  const handleSendMessage = () => {
    if (!newMessage.trim() || !selectedThread) return;

    sendMessageMutation.mutate({
      threadId: selectedThread.thread_id,
      content: newMessage,
      messageType: 'general',
    });
  };

  const handleUseAiSuggestion = (suggestion: string) => {
    setNewMessage(suggestion);
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-gray-900">消息中心</h1>
          <p className="text-muted-foreground mt-1">管理客户沟通和项目消息</p>
        </div>
        {unreadCount > 0 && (
          <Badge variant="destructive" className="gap-1">
            <Bell className="h-3 w-3" />
            {unreadCount} 条未读消息
          </Badge>
        )}
      </div>

      {(threadsError || messagesError || sendMessageMutation.error) && (
        <p role="alert" className="text-red-600">
          {String(threadsError || messagesError || sendMessageMutation.error)}
        </p>
      )}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 h-[calc(100vh-300px)]">
        {/* Thread List */}
        <Card className="lg:col-span-1 flex flex-col">
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2">
              <Search className="h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="搜索项目..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-8"
              />
            </div>
            <Tabs value={filter} onValueChange={(v) => setFilter(v as 'all' | 'unread')}>
              <TabsList className="w-full h-8">
                <TabsTrigger value="all" className="flex-1 text-xs">
                  全部
                </TabsTrigger>
                <TabsTrigger value="unread" className="flex-1 text-xs">
                  未读 ({unreadCount})
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </CardHeader>
          <ScrollArea className="flex-1">
            <div className="space-y-2 p-4 pt-0">
              {isLoading ? (
                <div className="text-center text-muted-foreground py-8">加载中...</div>
              ) : filteredThreads.length === 0 ? (
                <div className="text-center text-muted-foreground py-8">暂无消息</div>
              ) : (
                filteredThreads.map((thread) => (
                  <div
                    key={thread.thread_id}
                    onClick={() => handleSelectThread(thread)}
                    className={`p-3 rounded-lg cursor-pointer transition-colors ${
                      selectedThread?.thread_id === thread.thread_id
                        ? 'bg-blue-50 border-blue-200 border'
                        : 'hover:bg-gray-50'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium truncate">{thread.project_title}</span>
                          {thread.unread_count > 0 && (
                            <Badge variant="destructive" className="text-xs px-1.5 py-0">
                              {thread.unread_count}
                            </Badge>
                          )}
                        </div>
                        <p className="text-sm text-muted-foreground truncate mt-1">
                          {thread.last_message?.content || ''}
                        </p>
                        <div className="flex items-center gap-2 mt-2">
                          <span className="text-xs text-muted-foreground">
                            {thread.last_message?.sender_name || ''}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {formatTime(thread.last_message?.created_at || '')}
                          </span>
                        </div>
                      </div>
                      <ChevronRight className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                    </div>
                  </div>
                ))
              )}
            </div>
          </ScrollArea>
        </Card>

        {/* Message Detail */}
        <Card className="lg:col-span-2 flex flex-col">
          {selectedThread ? (
            <>
              <CardHeader className="border-b">
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-lg">{selectedThread.project_title}</CardTitle>
                    <CardDescription>
                      {getMessageTypeBadge(selectedMessages.at(-1)?.message_type || '')}
                    </CardDescription>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="ghost" size="icon">
                      <Archive className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="icon">
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </CardHeader>

              <ScrollArea className="flex-1 p-4">
                <div className="space-y-4">
                  {selectedMessages.map((message) => (
                    <div
                      key={message.id}
                      className={`flex gap-3 ${message.sender_name === 'Me' ? 'flex-row-reverse' : ''}`}
                    >
                      <Avatar className="h-8 w-8">
                        <AvatarFallback>
                          {message.sender_name
                            .split(' ')
                            .map((n) => n[0])
                            .join('')}
                        </AvatarFallback>
                      </Avatar>
                      <div
                        className={`flex flex-col gap-1 max-w-[70%] ${message.sender_name === 'Me' ? 'items-end' : ''}`}
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-medium">{message.sender_name}</span>
                          <span className="text-xs text-muted-foreground">
                            {formatTime(message.created_at)}
                          </span>
                          {message.is_read && <CheckCheck className="h-3 w-3 text-blue-500" />}
                        </div>
                        <div
                          className={`p-3 rounded-lg ${
                            message.sender_name === 'Me' ? 'bg-blue-500 text-white' : 'bg-gray-100'
                          }`}
                        >
                          <p className="text-sm">{message.content}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </ScrollArea>

              {/* AI Suggestions */}
              {selectedMessages[selectedMessages.length - 1]?.ai_suggestions &&
                selectedMessages[selectedMessages.length - 1]?.sender_name !== 'Me' && (
                  <div className="border-t p-4 bg-gray-50">
                    <div className="flex items-center gap-2 mb-2">
                      <Sparkles className="h-4 w-4 text-purple-500" />
                      <span className="text-sm font-medium">AI 建议回复</span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {selectedMessages[selectedMessages.length - 1]?.ai_suggestions?.map(
                        (suggestion, index) => (
                          <Button
                            key={index}
                            variant="outline"
                            size="sm"
                            onClick={() => handleUseAiSuggestion(suggestion)}
                            className="text-xs"
                          >
                            {suggestion.substring(0, 50)}...
                          </Button>
                        )
                      )}
                    </div>
                  </div>
                )}

              {/* Message Input */}
              <div className="border-t p-4">
                <div className="flex gap-2">
                  <Textarea
                    placeholder="输入消息..."
                    value={newMessage}
                    onChange={(e) => setNewMessage(e.target.value)}
                    className="min-h-[60px] resize-none"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleSendMessage();
                      }
                    }}
                  />
                  <Button
                    size="icon"
                    onClick={handleSendMessage}
                    disabled={!newMessage.trim() || sendMessageMutation.isPending}
                  >
                    <Send className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center text-muted-foreground">
                <MessageSquare className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <p>选择一个对话查看消息</p>
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
