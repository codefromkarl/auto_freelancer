'use client';

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Save, Play, RotateCcw, Copy, Plus, Trash2, Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  getPromptTemplates,
  updatePromptTemplate,
  createPromptTemplate,
  deletePromptTemplate,
} from '@/lib/api';

// Map tabs to API categories
const TAB_TO_CATEGORY: Record<string, string> = {
  scoring: 'scoring',
  personas: 'proposal',
  replies: 'message',
};

export default function PromptsPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState('scoring');
  const [selectedId, setSelectedId] = useState<string>(''); // string to work with Select value
  const [content, setContent] = useState('');
  const [testOutput, setTestOutput] = useState('');
  const [localName, setLocalName] = useState('');

  // Fetch prompts
  const { data: prompts = [], isLoading } = useQuery({
    queryKey: ['prompts', activeTab],
    queryFn: () => getPromptTemplates(TAB_TO_CATEGORY[activeTab]),
  });

  // Effect to select first prompt on load or when tab changes
  useEffect(() => {
    if (prompts.length > 0) {
      // If nothing selected, or selected ID not in current list
      const currentSelected = prompts.find((p) => p.id.toString() === selectedId);
      if (!selectedId || !currentSelected) {
        const first = prompts[0];
        setSelectedId(first.id.toString());
        setContent(first.content);
        setLocalName(first.name);
      }
    } else {
      // No prompts in this category
      setSelectedId('');
      setContent('');
      setLocalName('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prompts]);

  // Handle selection change
  const handleSelect = (idStr: string) => {
    const prompt = prompts.find((p) => p.id.toString() === idStr);
    if (prompt) {
      setSelectedId(idStr);
      setContent(prompt.content);
      setLocalName(prompt.name);
      setTestOutput('');
    }
  };

  // Mutations
  const updateMutation = useMutation({
    mutationFn: (data: { id: number; content: string; name: string }) =>
      updatePromptTemplate(data.id, { content: data.content, name: data.name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompts'] });
      alert('提示词模板已保存');
    },
    onError: (err) => {
      alert('保存失败: ' + err);
    },
  });

  const createMutation = useMutation({
    mutationFn: (category: string) =>
      createPromptTemplate({
        name: 'New Template',
        category: category as 'scoring' | 'proposal' | 'message' | 'general',
        content: 'Write your prompt here...',
        variables: [],
        is_active: true,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompts'] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deletePromptTemplate(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompts'] });
      setSelectedId('');
      setContent('');
      setLocalName('');
    },
  });

  const handleSave = () => {
    if (!selectedId) return;
    updateMutation.mutate({
      id: parseInt(selectedId),
      content,
      name: localName,
    });
  };

  const handleCreate = () => {
    createMutation.mutate(TAB_TO_CATEGORY[activeTab]);
  };

  const handleDelete = () => {
    if (!selectedId) return;
    if (confirm('Are you sure you want to delete this template?')) {
      deleteMutation.mutate(parseInt(selectedId));
    }
  };

  const handleTest = () => {
    // Mock testing
    setTestOutput(
      `Thinking...\n\nResult: This is a simulated output using template "${localName}".\n- Point 1: Analysis complete.\n- Point 2: Score 8/10.\n\n(Backend integration for testing not yet implemented)`
    );
  };

  const handleReset = () => {
    if (selectedId) {
      handleSelect(selectedId);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">提示词工程</h1>
        <p className="text-gray-500">管理和优化 AI 系统的 Prompt 模板</p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="grid w-full grid-cols-3 mb-6">
          <TabsTrigger value="scoring">评分与分析</TabsTrigger>
          <TabsTrigger value="personas">投标角色 (Personas)</TabsTrigger>
          <TabsTrigger value="replies">AI 回复生成</TabsTrigger>
        </TabsList>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left: Selection & Editor */}
          <div className="lg:col-span-2 space-y-6">
            <Card className="h-full flex flex-col">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
                <div className="space-y-1">
                  <CardTitle>编辑模板</CardTitle>
                  <CardDescription>选择并修改当前提示词</CardDescription>
                </div>
                <div className="flex items-center gap-2">
                  {isLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Select
                      value={selectedId}
                      onValueChange={handleSelect}
                      disabled={prompts.length === 0}
                    >
                      <SelectTrigger className="w-[180px]">
                        <SelectValue placeholder={prompts.length === 0 ? '无模板' : '选择模板'} />
                      </SelectTrigger>
                      <SelectContent>
                        {prompts.map((p) => (
                          <SelectItem key={p.id} value={p.id.toString()}>
                            {p.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={handleCreate}
                    disabled={createMutation.isPending}
                    title="新建模板"
                  >
                    <Plus className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="icon"
                    className="text-red-500 hover:text-red-600"
                    onClick={handleDelete}
                    disabled={!selectedId || deleteMutation.isPending}
                    title="删除模板"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col gap-4">
                <div className="flex gap-2 items-center">
                  <span className="text-sm font-medium">名称:</span>
                  <input
                    className="flex-1 p-2 border rounded-md text-sm"
                    value={localName}
                    onChange={(e) => setLocalName(e.target.value)}
                    placeholder="模板名称"
                  />
                </div>
                <textarea
                  className="flex-1 min-h-[400px] w-full p-4 rounded-md border border-gray-200 bg-gray-50 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  spellCheck={false}
                  placeholder="在此输入提示词内容..."
                />
                <div className="flex justify-between items-center pt-2">
                  <Button variant="outline" size="sm" onClick={handleReset} disabled={!selectedId}>
                    <RotateCcw className="h-4 w-4 mr-2" />
                    重置
                  </Button>
                  <Button
                    onClick={handleSave}
                    className="gap-2"
                    disabled={!selectedId || updateMutation.isPending}
                  >
                    {updateMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4" />
                    )}
                    保存更改
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Right: Testing Panel */}
          <div className="space-y-6">
            <Card className="h-full flex flex-col">
              <CardHeader>
                <CardTitle>测试控制台</CardTitle>
                <CardDescription>实时测试提示词效果</CardDescription>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col gap-4">
                <div className="space-y-2">
                  <label className="text-xs font-medium text-gray-500 uppercase">
                    测试输入 (Mock Context)
                  </label>
                  <textarea
                    className="w-full h-32 p-3 rounded-md border border-gray-200 text-sm resize-none"
                    placeholder="在此输入测试用的项目描述或上下文..."
                    defaultValue="Looking for a Python developer to build a scraping bot."
                  />
                </div>

                <Button
                  onClick={handleTest}
                  className="w-full gap-2"
                  variant="secondary"
                  disabled={!selectedId}
                >
                  <Play className="h-4 w-4" />
                  运行测试
                </Button>

                <div className="flex-1 bg-gray-900 rounded-md p-4 overflow-auto">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-gray-400 font-mono">OUTPUT</span>
                    <Copy className="h-3 w-3 text-gray-500 cursor-pointer hover:text-white" />
                  </div>
                  <pre className="text-green-400 font-mono text-xs whitespace-pre-wrap">
                    {testOutput || '// 等待执行...'}
                  </pre>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </Tabs>
    </div>
  );
}
