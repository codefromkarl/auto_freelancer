import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Project } from '@/lib/types';
import { ArrowUpRight, Clock, DollarSign, Star } from 'lucide-react';
import Link from 'next/link';
import { cn } from '@/lib/utils';

interface ProjectCardProps {
  project: Project;
}

export function ProjectCard({ project }: ProjectCardProps) {
  return (
    <Card className="hover:shadow-md transition-shadow">
      <CardHeader className="pb-3">
        <div className="flex justify-between items-start gap-4">
          <CardTitle className="text-lg font-semibold leading-tight line-clamp-2">
            <Link href={`/projects/${project.id}`} className="hover:text-primary transition-colors">
              {project.title}
            </Link>
          </CardTitle>
          <Badge variant={project.status === 'active' ? 'default' : 'secondary'} className="shrink-0">
            {project.status === 'active' ? '开放' : project.status}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="pb-3">
        <div className="flex flex-wrap gap-4 text-sm text-muted-foreground mb-3">
          <div className="flex items-center gap-1">
            <DollarSign className="w-4 h-4" />
            <span className="font-medium text-foreground">
              {project.currency_code} {project.budget_minimum} - {project.budget_maximum}
            </span>
          </div>
          {project.ai_score !== undefined && (
            <div className="flex items-center gap-1">
              <Star
                className={cn(
                  'w-4 h-4',
                  (project.ai_score || 0) > 7 ? 'text-yellow-500 fill-yellow-500' : 'text-gray-400'
                )}
              />
              <span
                className={cn(
                  'font-medium',
                  (project.ai_score || 0) > 7 ? 'text-yellow-600' : 'text-foreground'
                )}
              >
                {project.ai_score.toFixed(1)}
              </span>
            </div>
          )}
          <div className="flex items-center gap-1">
            <Clock className="w-4 h-4" />
            <span>{new Date(project.submitdate || '').toLocaleDateString()}</span>
          </div>
        </div>
        <p className="text-sm text-muted-foreground line-clamp-2">{project.description}</p>
      </CardContent>
      <CardFooter className="pt-0">
        <Button variant="ghost" size="sm" className="ml-auto gap-2" asChild>
          <Link href={`/projects/${project.id}`}>
            查看详情 <ArrowUpRight className="w-4 h-4" />
          </Link>
        </Button>
      </CardFooter>
    </Card>
  );
}
