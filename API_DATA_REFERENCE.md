# Graph API Data Reference

Generated: 2026-05-21 17:05
Email addresses are masked (us***@domain.com).

This document shows the **actual fields returned** by each Graph API method,
based on a live test against a real M365 account.
Used to design the v2 context layer (what data gets fed to AI).

---

## get_me()
**Method:** `get_me()`

**Fields returned (1 total):**
```json
{
  "@odata.context": "https://graph.microsoft.com/v1.0/$metadata#users/$entity",
  "businessPhones": [],
  "displayName": "Jason Hao",
  "givenName": "Jason",
  "jobTitle": null,
  "mail": "Ja***@ipsconsultancy.ca",
  "mobilePhone": null,
  "officeLocation": null,
  "preferredLanguage": null,
  "surname": "Hao",
  "userPrincipalName": "Ja***@ipsconsultancy.ca",
  "id": "cd2162aa-61f2-4d28-bce1-dc2332a0a97b"
}
```

**All keys:** `@odata.context, businessPhones, displayName, givenName, jobTitle, mail, mobilePhone, officeLocation, preferredLanguage, surname, userPrincipalName, id`


---

## get_mailbox_timezone()
**Method:** `get_mailbox_timezone()`

**Fields returned (1 total):**
```json
{
  "timezone": "UTC"
}
```

**All keys:** `timezone`


---

## get_messages(top=2) — full body included
**Method:** `get_messages(top)`

**Fields returned (2 total):**
```json
{
  "id": "AAMkAGU5NGQyMjk4LWZmYmUtNDY4ZS1hNjljLTU5Yjc3ODczMGZhYgBGAAAAAABNcASK_-R2RKpDKyeyUXELBwClOeKFwKMOTZvhVkvhNjVnAAAAAAEMAAClOeKFwKMOTZvhVkvhNjVnAAAWO1RSAAA=",
  "receivedDateTime": "2026-05-21T12:31:07Z",
  "hasAttachments": false,
  "subject": "Audrey AI sent a message",
  "bodyPreview": "\ud83d\udcca Business Intelligence \ud83d\udfe2 Da***@ipsconsultancy.ca \u2014 active \u2014 Primary champion for IPS Consultancy... \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c  \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c  \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c  \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c  \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c  \u200c \u200c \u200c ",
  "importance": "normal",
  "conversationId": "AAQkAGU5NGQyMjk4LWZmYmUtNDY4ZS1hNjljLTU5Yjc3ODczMGZhYgAQABzsZQAKZyJKugjEahB2nUk=",
  "isRead": true,
  "from": {
    "emailAddress": {
      "name": "Audrey AI in Teams",
      "address": "no***@teams.mail.microsoft"
    }
  },
  "ccRecipients": []
}
```

**All keys:** `id, receivedDateTime, hasAttachments, subject, bodyPreview, importance, conversationId, isRead, from, ccRecipients`


---

## get_inbox_conv_since(days=7) — $select fields
**Method:** `get_inbox_conv_since(days)`

**Fields returned (46 total):**
```json
{
  "id": "AAMkAGU5NGQyMjk4LWZmYmUtNDY4ZS1hNjljLTU5Yjc3ODczMGZhYgBGAAAAAABNcASK_-R2RKpDKyeyUXELBwClOeKFwKMOTZvhVkvhNjVnAAAAAAEMAAClOeKFwKMOTZvhVkvhNjVnAAAWO1RSAAA=",
  "receivedDateTime": "2026-05-21T12:31:07Z",
  "subject": "Audrey AI sent a message",
  "bodyPreview": "\ud83d\udcca Business Intelligence \ud83d\udfe2 Da***@ipsconsultancy.ca \u2014 active \u2014 Primary champion for IPS Consultancy... \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c  \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c  \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c  \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c  \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c \u200c  \u200c \u200c \u200c ",
  "conversationId": "AAQkAGU5NGQyMjk4LWZmYmUtNDY4ZS1hNjljLTU5Yjc3ODczMGZhYgAQABzsZQAKZyJKugjEahB2nUk=",
  "from": {
    "emailAddress": {
      "name": "Audrey AI in Teams",
      "address": "no***@teams.mail.microsoft"
    }
  }
}
```

**All keys:** `id, receivedDateTime, subject, bodyPreview, conversationId, from`


---

## get_sent_messages_since(days=7)
**Method:** `get_sent_messages_since(days)`

**Fields returned (2 total):**
```json
{
  "id": "AAMkAGU5NGQyMjk4LWZmYmUtNDY4ZS1hNjljLTU5Yjc3ODczMGZhYgBGAAAAAABNcASK_-R2RKpDKyeyUXELBwClOeKFwKMOTZvhVkvhNjVnAAAAAAEJAAClOeKFwKMOTZvhVkvhNjVnAAATr0UOAAA=",
  "sentDateTime": "2026-05-17T18:06:39Z",
  "subject": "Follow-up: Team catch up",
  "bodyPreview": "Hi Jason,\r\n\r\nThanks for leading our productive team catch-up on May 17th. We had a great discussion, reaffirming our current CRM strategy and making key decisions, including prioritizing specific electrical engineering use cases for immediate development.",
  "conversationId": "AAQkAGU5NGQyMjk4LWZmYmUtNDY4ZS1hNjljLTU5Yjc3ODczMGZhYgAQAPH5wC-i48tNrFha6Mfio7c=",
  "toRecipients": [
    {
      "emailAddress": {
        "name": "be***@techcorp.com",
        "address": "be***@techcorp.com"
      }
    }
  ]
}
```

**All keys:** `id, sentDateTime, subject, bodyPreview, conversationId, toRecipients`


---

## get_flagged_messages(days=90) — flag object
**Method:** `get_flagged_messages(days)`

_No results returned (empty list or None)_


---

## get_inbox_metadata_since(days=30) — lightweight, 4 fields
**Method:** `get_inbox_metadata_since(days)`

**Fields returned (646 total):**
```json
{
  "id": "AAMkAGU5NGQyMjk4LWZmYmUtNDY4ZS1hNjljLTU5Yjc3ODczMGZhYgBGAAAAAABNcASK_-R2RKpDKyeyUXELBwClOeKFwKMOTZvhVkvhNjVnAAAAAAEMAAClOeKFwKMOTZvhVkvhNjVnAAAWO1RSAAA=",
  "receivedDateTime": "2026-05-21T12:31:07Z",
  "subject": "Audrey AI sent a message",
  "from": {
    "emailAddress": {
      "name": "Audrey AI in Teams",
      "address": "no***@teams.mail.microsoft"
    }
  }
}
```

**All keys:** `id, receivedDateTime, subject, from`


---

## message attachments — /me/messages/{id}/attachments
**Method:** `get('/me/messages/{id}/attachments')`

**Fields returned (1 total):**
```json
{
  "@odata.type": "#microsoft.graph.fileAttachment",
  "@odata.mediaContentType": "image/webp",
  "id": "AAMkAGU5NGQyMjk4LWZmYmUtNDY4ZS1hNjljLTU5Yjc3ODczMGZhYgBGAAAAAABNcASK_-R2RKpDKyeyUXELBwClOeKFwKMOTZvhVkvhNjVnAAAAAAEMAAClOeKFwKMOTZvhVkvhNjVnAAAUMuWpAAABEgAQALwcfrYAB39AspRqLwte15k=",
  "lastModifiedDateTime": "2026-05-19T03:40:31Z",
  "name": "hand-holding-restaurant-receipt-showing-food-order-close-up-detailing-items-total-cost-412904372.webp",
  "contentType": "image/webp",
  "size": 27178,
  "isInline": false,
  "contentId": "f_mpc34gi90",
  "contentLocation": null,
  "contentBytes": "UklGRvZnAABXRUJQVlA4IOpnAADwXgKdASogA1gCPpFEnUwloyKwIZJ5egASCWdtW97dT7HGt/s6XrO32xHzlvNXKR1wERf1srJSbyTv7kj9r4gR3D/R8GPsn+q9gn9ivVIzTXEvNe6WL5zNJWJH3pL9V5tb4np33HPO83lneyPybyt/Mf8Dtb/nfNIsA8Mf61yw853mz9E+wR7E87Gcvz9oK/TP8B5wn1f/f/z/rv9lP2G+AHzO/5v6veYh+C/3nsEfzj/Afsp7wf+95lv17/l+wn+fv+97XnpACck8E2Qz\u2026[truncated]"
}
```

**All keys:** `@odata.type, @odata.mediaContentType, id, lastModifiedDateTime, name, contentType, size, isInline, contentId, contentLocation, contentBytes`


---

## get_calendar_view(today, tomorrow) — today's meetings
**Method:** `get_calendar_view(start, end)`

**Fields returned (1 total):**
```json
{
  "id": "AAMkAGU5NGQyMjk4LWZmYmUtNDY4ZS1hNjljLTU5Yjc3ODczMGZhYgBGAAAAAABNcASK_-R2RKpDKyeyUXELBwClOeKFwKMOTZvhVkvhNjVnAAAAAAENAAClOeKFwKMOTZvhVkvhNjVnAAAWO331AAA=",
  "subject": "update ",
  "bodyPreview": "________________________________________________________________________________\r\nMicrosoft Teams meeting\r\nJoin: https://teams.microsoft.com/meet/255438568539454?p=RoKkik7MMcsk83RpH1\r\nMeeting ID: 255 438 568 539 454\r\nPasscode: bq2qf3ZU\r\n________________",
  "isAllDay": false,
  "start": {
    "dateTime": "2026-05-21T14:30:00.0000000",
    "timeZone": "UTC"
  },
  "end": {
    "dateTime": "2026-05-21T15:00:00.0000000",
    "timeZone": "UTC"
  },
  "location": {
    "displayName": "Microsoft Teams Meeting",
    "locationType": "default",
    "uniqueId": "Microsoft Teams Meeting",
    "uniqueIdType": "private"
  },
  "attendees": [
    {
      "type": "required",
      "status": {
        "response": "none",
        "time": "0001-01-01T00:00:00Z"
      },
      "emailAddress": {
        "name": "Daniel Bin Zhang",
        "address": "Da***@ipsconsultancy.ca"
      }
    },
    {
      "type": "required",
      "status": {
        "response": "none",
        "time": "0001-01-01T00:00:00Z"
      },
      "emailAddress": {
        "name": "Jason Hao",
        "address": "Ja***@ipsconsultancy.ca"
      }
    }
  ]
}
```

**All keys:** `id, subject, bodyPreview, isAllDay, start, end, location, attendees`


---

## search_drive('mp4') — drive item structure
**Method:** `search_drive(query)`

**Fields returned (4 total):**
```json
{
  "createdDateTime": "2026-05-09T14:32:56Z",
  "id": "01NVGOFCM67XC5CJRKPVD2BRF24ZDUE3OD",
  "lastModifiedDateTime": "2026-05-09T15:48:56Z",
  "name": "Team catch up-20260509_103255-Meeting Recording.mp4",
  "webUrl": "https://ipsconsultancyca-my.sharepoint.com/personal/jason_hao_ipsconsultancy_ca/Documents/Forms/DispForm.aspx?ID=14",
  "size": 511240511,
  "createdBy": {
    "user": {
      "email": "",
      "displayName": "SharePoint App"
    }
  },
  "lastModifiedBy": {
    "user": {
      "email": "",
      "displayName": "SharePoint App"
    }
  },
  "parentReference": {
    "driveType": "business",
    "driveId": "b!kYBA-yN9hUKKbNZi_Hj1DFdtKy4f6A5NnAnw4Yn0umn28Jjaii6oTKrmbdg7rCsQ",
    "id": "01NVGOFCM7R74MUEDQPNBYKPXWCT65BWOT",
    "siteId": "fb408091-7d23-4285-8a6c-d662fc78f50c"
  },
  "file": {
    "mimeType": "video/mp4",
    "hashes": {}
  },
  "fileSystemInfo": {
    "createdDateTime": "2026-05-09T14:32:56Z",
    "lastModifiedDateTime": "2026-05-09T15:48:56Z"
  },
  "searchResult": {}
}
```

**All keys:** `createdDateTime, id, lastModifiedDateTime, name, webUrl, size, createdBy, lastModifiedBy, parentReference, file, fileSystemInfo, searchResult`


---

## get_shared_recordings() — shared .mp4 files
**Method:** `get_shared_recordings()`

**Fields returned (1 total):**
```json
{
  "createdDateTime": "2026-05-21T14:37:06Z",
  "id": "01WI5DMRAWISTKISP72RBI7QLPT3RYEZ4L",
  "name": "update-20260521_073706-Meeting Recording.mp4",
  "size": 157562,
  "remoteItem": {
    "createdDateTime": "2026-05-21T14:37:06Z",
    "id": "01WI5DMRAWISTKISP72RBI7QLPT3RYEZ4L",
    "lastModifiedDateTime": "2026-05-21T15:11:16Z",
    "name": "update-20260521_073706-Meeting Recording.mp4",
    "size": 157562,
    "webDavUrl": "https://ipsconsultancyca-my.sharepoint.com/personal/daniel_bin_zhang_ipsconsultancy_ca/Documents/Recordings/update-20260521_073706-Meeting%20Recording.mp4",
    "webUrl": "https://ipsconsultancyca-my.sharepoint.com/personal/daniel_bin_zhang_ipsconsultancy_ca/Documents/Recordings/update-20260521_073706-Meeting%20Recording.mp4",
    "file": {
      "mimeType": "video/mp4",
      "hashes": {}
    },
    "fileSystemInfo": {
      "createdDateTime": "2026-05-21T14:37:06Z",
      "lastModifiedDateTime": "2026-05-21T15:11:16Z"
    },
    "parentReference": {
      "driveType": "business",
      "driveId": "b!p3KtpfCYb0ieHtKsvW_Srtf0ykp9BpxGtWM0jeeqK7xkI8b5xXMbTIKhTtWSqhur",
      "id": "01WI5DMRHDOLOVGTIAZRD3XFE6OYCNTTUQ",
      "siteId": "a5ad72a7-98f0-486f-9e1e-d2acbd6fd2ae"
    },
    "shared": {
      "scope": "users",
      "sharedDateTime": "2026-05-21T15:11:45Z",
      "sharedBy": {
        "user": {
          "email": "Da***@ipsconsultancy.ca",
          "id": "Da***@ipsconsultancy.ca",
          "displayName": "Daniel Bin Zhang"
        }
      }
    },
    "sharepointIds": {
      "listId": "f9c62364-73c5-4c1b-82a1-4ed592aa1bab",
      "listItemId": "40",
      "listItemUniqueId": "a4a64416-ff49-42d4-8fc1-6f9ee382678b",
      "siteId": "a5ad72a7-98f0-486f-9e1e-d2acbd6fd2ae",
      "siteUrl": "https://ipsconsultancyca-my.sharepoint.com/personal/daniel_bin_zhang_ipsconsultancy_ca",
      "tenantId": "08d3a3f1-0366-451e-98ce-74626f1bf75f",
      "webId": "4acaf4d7-067d-469c-b563-348de7aa2bbc"
    }
  }
}
```

**All keys:** `createdDateTime, id, name, size, remoteItem`


---

## OneDrive root children — folder/file item structure
**Method:** `list_drive_folder('root')`

**Fields returned (3 total):**
```json
{
  "createdDateTime": "2026-05-08T00:06:24Z",
  "id": "01NVGOFCLFW7SRX3NJ4ZF34J2FKZ3VIYSK",
  "name": "Attachments",
  "folder": {
    "childCount": 0
  },
  "size": 0
}
```

**All keys:** `createdDateTime, id, name, folder, size`


---

## To-Do lists — /me/todo/lists
**Method:** `get('/me/todo/lists')`

**Fields returned (1 total):**
```json
{
  "displayName": "Tasks",
  "isOwner": true,
  "isShared": false,
  "wellknownListName": "defaultList",
  "id": "AAMkAGU5NGQyMjk4LWZmYmUtNDY4ZS1hNjljLTU5Yjc3ODczMGZhYgAuAAAAAABNcASK_-R2RKpDKyeyUXELAQClOeKFwKMOTZvhVkvhNjVnAAAAAAESAAA="
}
```

**All keys:** `displayName, isOwner, isShared, wellknownListName, id`


---

## Teams 1:1 chats — /me/chats
**Method:** `find_chat_with_user()`

**Fields returned (2 total):**
```json
{
  "id": "19:c3***@unq.gbl.spaces",
  "chatType": "oneOnOne",
  "members@odata.context": "https://graph.microsoft.com/v1.0/$metadata#users('cd2162aa-61f2-4d28-bce1-dc2332a0a97b')/chats('19%3Ac3030d72-2181-4fc1-8ca6-033215124ed3_cd2162aa-61f2-4d28-bce1-dc2332a0a97b%40unq.gbl.spaces')/members",
  "members": [
    {
      "@odata.type": "#microsoft.graph.aadUserConversationMember",
      "id": "MCMjMCMjMDhkM2EzZjEtMDM2Ni00NTFlLTk4Y2UtNzQ2MjZmMWJmNzVmIyMxOTpjMzAzMGQ3Mi0yMTgxLTRmYzEtOGNhNi0wMzMyMTUxMjRlZDNfY2QyMTYyYWEtNjFmMi00ZDI4LWJjZTEtZGMyMzMyYTBhOTdiQHVucS5nYmwuc3BhY2VzIyNjZDIxNjJhYS02MWYyLTRkMjgtYmNlMS1kYzIzMzJhMGE5N2I=",
      "roles": [
        "owner"
      ],
      "displayName": "Jason Hao",
      "visibleHistoryStartDateTime": "0001-01-01T00:00:00Z",
      "userId": "cd2162aa-61f2-4d28-bce1-dc2332a0a97b",
      "email": "Ja***@ipsconsultancy.ca",
      "tenantId": "08d3a3f1-0366-451e-98ce-74626f1bf75f"
    },
    {
      "@odata.type": "#microsoft.graph.aadUserConversationMember",
      "id": "MCMjMCMjMDhkM2EzZjEtMDM2Ni00NTFlLTk4Y2UtNzQ2MjZmMWJmNzVmIyMxOTpjMzAzMGQ3Mi0yMTgxLTRmYzEtOGNhNi0wMzMyMTUxMjRlZDNfY2QyMTYyYWEtNjFmMi00ZDI4LWJjZTEtZGMyMzMyYTBhOTdiQHVucS5nYmwuc3BhY2VzIyNjMzAzMGQ3Mi0yMTgxLTRmYzEtOGNhNi0wMzMyMTUxMjRlZDM=",
      "roles": [
        "owner"
      ],
      "displayName": "Audrey AI",
      "visibleHistoryStartDateTime": "0001-01-01T00:00:00Z",
      "userId": "c3030d72-2181-4fc1-8ca6-033215124ed3",
      "email": "Au***@ipsconsultancy.ca",
      "tenantId": "08d3a3f1-0366-451e-98ce-74626f1bf75f"
    }
  ]
}
```

**All keys:** `id, chatType, members@odata.context, members`
