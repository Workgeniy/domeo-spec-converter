using DomeoSpec.Application.Common;
using Microsoft.AspNetCore.Diagnostics;
using Microsoft.AspNetCore.Mvc;

namespace DomeoSpec.Api.Infrastructure;

/// <summary>
/// Маппит исключения сценариев в ProblemDetails. Сбой ядра — 503 с Retry-After, а не 500:
/// данные целы, запрос стоит повторить. В журнал как проблема пишется только 500.
/// </summary>
public sealed class GlobalExceptionHandler(IProblemDetailsService problemDetails, ILogger<GlobalExceptionHandler> logger)
    : IExceptionHandler
{
    public async ValueTask<bool> TryHandleAsync(HttpContext httpContext, Exception exception, CancellationToken cancellationToken)
    {
        var (status, title, code) = exception switch
        {
            ValidationFailedException => (StatusCodes.Status400BadRequest, "Bad Request", ErrorCodes.ValidationFailed),
            NotFoundException => (StatusCodes.Status404NotFound, "Not Found", ErrorCodes.NotFound),
            EngineFailureException => (StatusCodes.Status422UnprocessableEntity, "Unprocessable Entity", ErrorCodes.EngineFailed),
            ServiceUnavailableException => (StatusCodes.Status503ServiceUnavailable, "Service Unavailable", ErrorCodes.ServiceUnavailable),
            _ => (StatusCodes.Status500InternalServerError, "Internal Server Error", ErrorCodes.Unexpected),
        };

        if (status == StatusCodes.Status500InternalServerError)
            logger.LogError(exception, "Необработанное исключение");
        else if (status == StatusCodes.Status503ServiceUnavailable)
        {
            logger.LogWarning(exception, "Ядро разбора недоступно: {Reason}", exception.Message);
            httpContext.Response.Headers.RetryAfter = "5";
        }

        httpContext.Response.StatusCode = status;
        var problem = new ProblemDetails
        {
            Status = status,
            Title = title,
            Detail = status == StatusCodes.Status500InternalServerError ? "Внутренняя ошибка сервера." : exception.Message,
        };
        problem.Extensions["code"] = code;

        return await problemDetails.TryWriteAsync(new ProblemDetailsContext
        {
            HttpContext = httpContext,
            ProblemDetails = problem,
            Exception = exception,
        });
    }
}
