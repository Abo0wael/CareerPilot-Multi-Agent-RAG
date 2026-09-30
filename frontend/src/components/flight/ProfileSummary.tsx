import type { ReactNode } from "react";
import type { CandidateProfile } from "@/lib/api";
import { Card, Chip } from "../ui";

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 font-mono text-xs uppercase tracking-[0.14em] text-muted">{title}</h3>
      {children}
    </div>
  );
}

/** The structured profile the ProfileAgent extracted from the CV. */
export function ProfileSummary({ profile }: { profile: CandidateProfile }) {
  return (
    <Card className="grid gap-6 p-5 sm:p-6 lg:grid-cols-[1fr_1.4fr]">
      <div className="flex flex-col gap-5">
        <div>
          <p className="font-display text-2xl font-semibold">{profile.name || "Candidate"}</p>
          {profile.summary && <p className="mt-2 text-sm text-muted">{profile.summary}</p>}
        </div>
        <Block title={`Skills (${profile.skills.length})`}>
          <div className="flex flex-wrap gap-1.5">
            {profile.skills.map((skill) => (
              <Chip key={skill}>{skill}</Chip>
            ))}
          </div>
        </Block>
        {profile.education.length > 0 && (
          <Block title="Education">
            <ul className="space-y-1 text-sm">
              {profile.education.map((ed) => (
                <li key={`${ed.degree}-${ed.institution}`}>
                  {ed.degree}
                  <span className="text-muted">{[ed.institution, ed.year].filter(Boolean).map((x) => ` · ${x}`)}</span>
                </li>
              ))}
            </ul>
          </Block>
        )}
      </div>
      <div className="flex flex-col gap-5">
        <Block title={`Experience (${profile.experiences.length})`}>
          <ul className="space-y-3">
            {profile.experiences.map((exp) => (
              <li key={`${exp.role}-${exp.company}-${exp.duration}`} className="border-l-2 border-line pl-3">
                <p className="text-sm font-medium">
                  {exp.role} <span className="font-normal text-muted">· {exp.company}</span>
                </p>
                <p className="font-mono text-xs text-muted">{exp.duration}</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-4 text-sm text-muted">
                  {exp.bullets.map((bullet) => (
                    <li key={bullet}>{bullet}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </Block>
        {profile.projects.length > 0 && (
          <Block title={`Projects (${profile.projects.length})`}>
            <ul className="space-y-2 text-sm">
              {profile.projects.map((project) => (
                <li key={project.name}>
                  <span className="font-medium">{project.name}</span>
                  {project.technologies.length > 0 && (
                    <span className="font-mono text-xs text-muted"> · {project.technologies.join(", ")}</span>
                  )}
                  {project.description && <p className="text-muted">{project.description}</p>}
                </li>
              ))}
            </ul>
          </Block>
        )}
      </div>
    </Card>
  );
}
