# API + фронт в одном образе. Контекст сборки — корень репозитория (нужны web/ и api/):
#   docker build -f api/Dockerfile -t domeo-spec-api .

# --- фронт ---
FROM node:20-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- сборка API ---
FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src
# Restore по csproj отдельно от исходников — слой с пакетами кешируется между сборками.
COPY api/src/DomeoSpec.Domain/DomeoSpec.Domain.csproj api/src/DomeoSpec.Domain/
COPY api/src/DomeoSpec.Application/DomeoSpec.Application.csproj api/src/DomeoSpec.Application/
COPY api/src/DomeoSpec.Infrastructure/DomeoSpec.Infrastructure.csproj api/src/DomeoSpec.Infrastructure/
COPY api/src/DomeoSpec.Api/DomeoSpec.Api.csproj api/src/DomeoSpec.Api/
RUN dotnet restore api/src/DomeoSpec.Api/DomeoSpec.Api.csproj
COPY api/src/ api/src/
RUN dotnet publish api/src/DomeoSpec.Api/DomeoSpec.Api.csproj -c Release -o /app/publish /p:UseAppHost=false --no-restore

# --- runtime ---
FROM mcr.microsoft.com/dotnet/aspnet:9.0
WORKDIR /app
COPY --from=build /app/publish ./
COPY --from=web /web/dist ./wwwroot
# Собранный фронт лежит в образе; в разработке API ищет web/dist рядом с репозиторием.
ENV Web__DistPath=/app/wwwroot \
    ASPNETCORE_URLS=http://+:8080
USER app
EXPOSE 8080
ENTRYPOINT ["dotnet", "DomeoSpec.Api.dll"]
